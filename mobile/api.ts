/**
 * PayShield Mobile - Centralized API Client
 * Automatically handles token injection, device identification (X-Device-ID),
 * error parsing, and session revocation on 401.
 */

import { API_BASE_URL } from "./config";
import { authStorage, PayShieldUserProfile } from "./authStorage";

export interface ApprovalItem {
  id: number;
  transaction_ref: string;
  transaction_type: string;
  amount: string;
  currency: string;
  source_bank: string;
  sender_name: string;
  sender_account_masked: string;
  recipient_name: string;
  recipient_account_masked: string;
  description: string;
  status: "PENDING" | "APPROVED" | "DENIED" | "EXPIRED";
  is_reported_fraud?: boolean;
  fraud_report_id?: string;
  expires_at: string;
  created_at: string;
}

export interface CyberCrimeReportResponse {
  message: string;
  complaint_ref: string;
  helpline: string;
  portal_url: string;
  approval_id: number;
  already_reported: boolean;
  reported_at?: string;
  summary?: {
    amount: string;
    currency: string;
    recipient_name: string;
    scam_category: string;
  };
}

export interface RequestOtpResponse {
  message: string;
  phone_number: string;
  expires_in_seconds: number;
  dev_otp?: string;
  warning?: string;
}

export interface RegisterResponse {
  message: string;
  phone_number: string;
  full_name: string;
  expires_in_seconds: number;
  dev_otp?: string;
  warning?: string;
}

export interface VerifyOtpResponse {
  message: string;
  token: string;
  expires_in_hours: number;
  user: PayShieldUserProfile;
}

export interface DeviceItem {
  id: number;
  device_id: string;
  device_name: string;
  platform: "ANDROID" | "IOS" | "WEB" | "OTHER";
  app_version: string;
  status: "ACTIVE" | "REVOKED";
  registered_at: string;
  last_active_at: string;
  revoked_at?: string;
  revocation_reason?: string;
}

export interface DeviceStatusResponse {
  has_active_device: boolean;
  active_device: DeviceItem | null;
  is_current_device_registered: boolean;
  current_device_status: "ACTIVE" | "REVOKED" | "UNREGISTERED";
}

export interface DeviceReplaceResponse {
  message: string;
  device: DeviceItem;
  token: string;
}

export interface DiscoveredAccount {
  bank_account_id: number;
  bank_customer_id: string;
  bank_name: string;
  account_number: string;
  account_number_masked: string;
  account_type: string;
  ifsc_code: string;
  balance?: string;
  currency?: string;
  customer_name?: string;
  is_already_linked?: boolean;
  link_id?: number;
}

export interface LinkedAccountItem {
  link_id: number;
  bank_name: string;
  bank_account_id?: number;
  bank_customer_id?: string;
  account_number_masked: string;
  account_type: string;
  is_verified: boolean;
  verification_status: string;
  linked_at: string;
}

/**
 * Low-level HTTP fetch wrapper with authorization and device header injection.
 */
async function apiFetch<T>(
  endpoint: string,
  options: RequestInit = {},
  requiresAuth: boolean = true
): Promise<T> {
  const url = `${API_BASE_URL}${endpoint}`;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };

  if (requiresAuth) {
    const token = authStorage.getToken();
    if (token) {
      headers["Authorization"] = `Token ${token}`;
    }
  }

  // Attach persistent device identifier
  const deviceId = authStorage.getDeviceId();
  if (deviceId) {
    headers["X-Device-ID"] = deviceId;
  }

  const response = await fetch(url, {
    ...options,
    headers,
  });

  if (response.status === 401 && requiresAuth) {
    authStorage.notifyAuthExpired();
    throw new Error("Session expired or unauthorized. Please sign in again.");
  }

  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    const errorMsg =
      (data as any).error ||
      (data as any).detail ||
      (data as any).message ||
      (typeof data === "object" ? Object.values(data).flat().join(" ") : null) ||
      `Request failed with status ${response.status}`;
    const err: any = new Error(errorMsg);
    err.code = (data as any).code;
    err.status = response.status;
    err.data = data;
    throw err;
  }

  return data as T;
}

export const api = {
  checkHealth: async (): Promise<{ status: string; message: string }> => {
    return apiFetch<{ status: string; message: string }>(
      "/api/health/",
      { method: "GET" },
      false
    );
  },

  register: async (
    fullName: string,
    phoneNumber: string
  ): Promise<RegisterResponse> => {
    return apiFetch<RegisterResponse>(
      "/api/auth/register/",
      {
        method: "POST",
        body: JSON.stringify({
          full_name: fullName.trim(),
          phone_number: phoneNumber.trim(),
        }),
      },
      false
    );
  },

  requestLoginOtp: async (
    phoneNumber: string
  ): Promise<RequestOtpResponse> => {
    return apiFetch<RequestOtpResponse>(
      "/api/auth/request-otp/",
      {
        method: "POST",
        body: JSON.stringify({ phone_number: phoneNumber.trim() }),
      },
      false
    );
  },

  verifyLoginOtp: async (
    phoneNumber: string,
    otp: string
  ): Promise<VerifyOtpResponse> => {
    const res = await apiFetch<VerifyOtpResponse>(
      "/api/auth/verify-otp/",
      {
        method: "POST",
        body: JSON.stringify({
          phone_number: phoneNumber.trim(),
          otp: otp.trim(),
        }),
      },
      false
    );
    authStorage.setSession(res.token, res.user);
    return res;
  },

  fetchProfile: async (): Promise<PayShieldUserProfile> => {
    return apiFetch<PayShieldUserProfile>("/api/auth/me/", { method: "GET" }, true);
  },

  // ---------------------------------------------------------------------------
  // BANK ACCOUNT DISCOVERY & LINKING (UPI ONBOARDING)
  // ---------------------------------------------------------------------------

  fetchLinkedAccounts: async (): Promise<LinkedAccountItem[]> => {
    const data = await apiFetch<any>("/api/banking/accounts/", { method: "GET" }, true);
    return Array.isArray(data) ? data : [];
  },

  discoverBankAccounts: async (): Promise<{
    phone_number: string;
    customer_name: string;
    accounts_count: number;
    accounts: DiscoveredAccount[];
  }> => {
    return apiFetch<{
      phone_number: string;
      customer_name: string;
      accounts_count: number;
      accounts: DiscoveredAccount[];
    }>("/api/banking/accounts/discover/", { method: "GET" }, true);
  },

  linkDiscoveredAccount: async (
    accountNumber: string,
    bankAccountId?: number
  ): Promise<{ message: string; link: LinkedAccountItem }> => {
    return apiFetch<{ message: string; link: LinkedAccountItem }>(
      "/api/banking/accounts/link-discovered/",
      {
        method: "POST",
        body: JSON.stringify({
          account_number: accountNumber,
          bank_account_id: bankAccountId,
        }),
      },
      true
    );
  },

  unlinkBankAccount: async (linkId: number): Promise<{ message: string; link_id: number }> => {
    return apiFetch<{ message: string; link_id: number }>(
      `/api/banking/accounts/${linkId}/unlink/`,
      {
        method: "POST",
      },
      true
    );
  },

  // ---------------------------------------------------------------------------
  // DEVICE REGISTRATION & BINDING ENDPOINTS
  // ---------------------------------------------------------------------------

  getDeviceStatus: async (): Promise<DeviceStatusResponse> => {
    return apiFetch<DeviceStatusResponse>("/api/devices/status/", { method: "GET" }, true);
  },

  registerDevice: async (
    deviceId: string,
    deviceName: string,
    platform: string,
    appVersion: string = "1.0.0"
  ): Promise<{ message: string; device: DeviceItem }> => {
    return apiFetch<{ message: string; device: DeviceItem }>(
      "/api/devices/register/",
      {
        method: "POST",
        body: JSON.stringify({
          device_id: deviceId,
          device_name: deviceName,
          platform,
          app_version: appVersion,
        }),
      },
      true
    );
  },

  updatePushToken: async (pushToken: string): Promise<{ message: string }> => {
    return apiFetch<{ message: string }>(
      "/api/devices/push-token/",
      {
        method: "POST",
        body: JSON.stringify({ push_token: pushToken }),
      },
      true
    );
  },

  requestDeviceReplacementOtp: async (): Promise<RequestOtpResponse> => {
    return apiFetch<RequestOtpResponse>(
      "/api/devices/replace/request-otp/",
      { method: "POST" },
      true
    );
  },

  replaceDevice: async (
    otp: string,
    deviceId: string,
    deviceName: string,
    platform: string,
    appVersion: string = "1.0.0"
  ): Promise<DeviceReplaceResponse> => {
    const res = await apiFetch<DeviceReplaceResponse>(
      "/api/devices/replace/",
      {
        method: "POST",
        body: JSON.stringify({
          otp: otp.trim(),
          device_id: deviceId,
          device_name: deviceName,
          platform,
          app_version: appVersion,
        }),
      },
      true
    );
    // Update active token in storage
    const user = authStorage.getUser();
    if (user) {
      authStorage.setSession(res.token, user);
    }
    return res;
  },

  revokeDevice: async (
    deviceId?: string,
    reason: string = "USER_REQUESTED"
  ): Promise<{ message: string }> => {
    return apiFetch<{ message: string }>(
      "/api/devices/revoke/",
      {
        method: "POST",
        body: JSON.stringify({ device_id: deviceId, reason }),
      },
      true
    );
  },

  // ---------------------------------------------------------------------------
  // APPROVALS & DECISIONS
  // ---------------------------------------------------------------------------

  fetchPendingApprovals: async (): Promise<ApprovalItem[]> => {
    const data = await apiFetch<any>("/api/approvals/", { method: "GET" }, true);
    return Array.isArray(data) ? data : data.results ?? [];
  },

  fetchApprovalHistory: async (): Promise<ApprovalItem[]> => {
    const data = await apiFetch<any>("/api/approvals/history/", { method: "GET" }, true);
    return Array.isArray(data) ? data : data.results ?? [];
  },

  decideApproval: async (
    approvalId: number,
    decision: "APPROVED" | "DENIED"
  ): Promise<{ message: string; decision: string }> => {
    return apiFetch<{ message: string; decision: string }>(
      `/api/approvals/${approvalId}/decide/`,
      {
        method: "POST",
        body: JSON.stringify({ decision }),
      },
      true
    );
  },

  reportCyberCrime: async (
    approvalId: number,
    category: string = "SUSPICIOUS_UNAUTHORIZED",
    notes: string = ""
  ): Promise<CyberCrimeReportResponse> => {
    return apiFetch<CyberCrimeReportResponse>(
      `/api/approvals/${approvalId}/report-fraud/`,
      {
        method: "POST",
        body: JSON.stringify({ category, notes }),
      },
      true
    );
  },

  logout: async (): Promise<void> => {
    try {
      await apiFetch<any>("/api/auth/logout/", { method: "POST" }, true);
    } catch {
      // Ignore network errors during logout
    } finally {
      authStorage.clearSession();
    }
  },
};
