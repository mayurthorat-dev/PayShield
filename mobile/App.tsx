import React, { useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Linking,
  Modal,
  Platform,
  Pressable,
  SafeAreaView,
  ScrollView,
  StatusBar,
  StyleSheet,
  Text,
  TextInput,
  Vibration,
  View,
} from "react-native";
import * as Notifications from "expo-notifications";
import * as Device from "expo-device";
import Constants from "expo-constants";

import {
  api,
  ApprovalItem,
  CyberCrimeReportResponse,
  DeviceItem,
  DiscoveredAccount,
  LinkedAccountItem,
} from "./api";
import { authStorage, PayShieldUserProfile } from "./authStorage";

Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldPlaySound: true,
    shouldSetBadge: true,
    shouldShowBanner: true,
    shouldShowList: true,
  }),
});

async function configureNotificationChannels() {
  if (Platform.OS === "android") {
    try {
      await Notifications.setNotificationChannelAsync("payshield-approvals", {
        name: "PayShield Approvals",
        importance: Notifications.AndroidImportance.MAX,
        vibrationPattern: [0, 500, 200, 500, 200, 500],
        lightColor: "#2563EB",
        enableVibrate: true,
        showBadge: true,
      });
    } catch (channelErr) {
      console.warn("Could not set notification channel:", channelErr);
    }
  }
}

async function registerForPushNotificationsAsync(): Promise<string | null> {
  if (Platform.OS === "web") return null;

  try {
    await configureNotificationChannels();

    const { status: existingStatus } = await Notifications.getPermissionsAsync();
    let finalStatus = existingStatus;
    if (existingStatus !== "granted") {
      const { status } = await Notifications.requestPermissionsAsync({
        ios: {
          allowAlert: true,
          allowBadge: true,
          allowSound: true,
        },
      });
      finalStatus = status;
    }

    if (finalStatus !== "granted") {
      console.log("[Push] Notification permission not granted (status:", finalStatus, ")");
      return null;
    }

    // Try to get Expo Push Token if EAS project ID is configured
    try {
      const projectId =
        Constants?.expoConfig?.extra?.eas?.projectId ??
        Constants?.easConfig?.projectId;

      const tokenData = await Notifications.getExpoPushTokenAsync(
        projectId ? { projectId } : undefined
      ).catch(() => null);

      if (tokenData && tokenData.data) {
        console.log("[Push] Expo push token obtained:", tokenData.data);
        return tokenData.data;
      }
    } catch (e) {
      console.log("[Push] Remote push token not available in this environment:", e);
    }

    // In standalone APK build with google-services.json, retrieve native FCM token
    try {
      const nativeToken = await Notifications.getDevicePushTokenAsync().catch(() => null);
      if (nativeToken && nativeToken.data) {
        console.log("[Push] Native FCM push token obtained:", nativeToken.data);
        return nativeToken.data;
      }
    } catch (e) {
      console.log("[Push] Native FCM token not available:", e);
    }

    return null;
  } catch (err) {
    console.warn("[Push] Error during push setup:", err);
    return null;
  }
}

type ScreenMode =
  | "WELCOME"
  | "LOGIN"
  | "REGISTER"
  | "VERIFY_OTP"
  | "DASHBOARD"
  | "DEVICE_REPLACEMENT";

const SCAM_CATEGORIES = [
  { id: "PHISHING_FAKE_LINK", label: "Phishing / Fake Link / APK", icon: "🎣" },
  { id: "IMPERSONATION", label: "Police / Bank Official Impersonation", icon: "👮" },
  { id: "QR_UPI_FRAUD", label: "QR Code / UPI Collect Request Fraud", icon: "📱" },
  { id: "INVESTMENT_JOB_SCAM", label: "Part-time Job / Crypto / Task Scam", icon: "💼" },
  { id: "SUSPICIOUS_UNAUTHORIZED", label: "Unauthorized / Unknown Transfer", icon: "⚠️" },
];

export default function App() {
  // Navigation & Session State
  const [currentScreen, setCurrentScreen] = useState<ScreenMode>("WELCOME");
  const [currentUser, setCurrentUser] = useState<PayShieldUserProfile | null>(null);
  const [isInitializing, setIsInitializing] = useState(true);
  const [backendStatus, setBackendStatus] = useState<string>("Checking backend...");

  // Device Binding State
  const [activeDeviceInfo, setActiveDeviceInfo] = useState<DeviceItem | null>(null);
  const [conflictDevice, setConflictDevice] = useState<DeviceItem | null>(null);
  const [deviceLoading, setDeviceLoading] = useState(false);
  const [replacementOtpSent, setReplacementOtpSent] = useState(false);
  const [replacementOtpInput, setReplacementOtpInput] = useState("");
  const [replacementDevOtp, setReplacementDevOtp] = useState<string | null>(null);

  // Bank Account Discovery & Linking State (UPI Onboarding)
  const [showBankModal, setShowBankModal] = useState(false);
  const [linkedAccounts, setLinkedAccounts] = useState<LinkedAccountItem[]>([]);
  const [discoveredAccounts, setDiscoveredAccounts] = useState<DiscoveredAccount[]>([]);
  const [loadingBankAccounts, setLoadingBankAccounts] = useState(false);
  const [linkingAccountId, setLinkingAccountId] = useState<number | null>(null);

  // Form states
  const [fullNameInput, setFullNameInput] = useState("");
  const [phoneInput, setPhoneInput] = useState("");
  const [consentAgreed, setConsentAgreed] = useState(false);
  const [otpInput, setOtpInput] = useState("");
  const [devOtpHint, setDevOtpHint] = useState<string | null>(null);
  const [authOrigin, setAuthOrigin] = useState<"LOGIN" | "REGISTER">("LOGIN");
  const [authLoading, setAuthLoading] = useState(false);

  // OTP cooldown timer (30s)
  const [resendCooldown, setResendCooldown] = useState(0);
  const cooldownTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Approvals & Dashboard state
  const [approvals, setApprovals] = useState<ApprovalItem[]>([]);
  const [loadingApprovals, setLoadingApprovals] = useState(false);
  const [decidingId, setDecidingId] = useState<number | null>(null);
  const [selectedApproval, setSelectedApproval] = useState<ApprovalItem | null>(null);

  // Tab Feed State: PENDING vs HISTORY
  const [feedTab, setFeedTab] = useState<"PENDING" | "HISTORY">("PENDING");
  const [historyApprovals, setHistoryApprovals] = useState<ApprovalItem[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(false);

  // Cyber Crime Scam Reporting State
  const [reportModalItem, setReportModalItem] = useState<ApprovalItem | null>(null);
  const [scamCategory, setScamCategory] = useState<string>("PHISHING_FAKE_LINK");
  const [scamNotes, setScamNotes] = useState<string>("");
  const [submittingReport, setSubmittingReport] = useState(false);
  const [complaintReceipt, setComplaintReceipt] = useState<CyberCrimeReportResponse | null>(null);

  // Device Info Modal
  const [showDeviceModal, setShowDeviceModal] = useState(false);

  // Set of approval IDs that have already alerted/vibrated to prevent duplicate alerts
  const notifiedApprovalsRef = useRef<Set<number>>(new Set());

  // Ticking state for live countdowns
  const [, setClockTick] = useState(0);

  // 1. Session Initialization and Backend Health Check
  useEffect(() => {
    let isMounted = true;

    async function init() {
      // Early setup of notification channels & sound config
      try {
        await configureNotificationChannels();
      } catch (e) {
        console.warn("Notification channel setup warning:", e);
      }

      // Check backend health
      try {
        await api.checkHealth();
        if (isMounted) setBackendStatus("Connected to PayShield Server ✓");
      } catch {
        if (isMounted) setBackendStatus("Offline: Could not connect to backend");
      }

      // Restore session and hardware device identifier from SecureStore
      const { user } = await authStorage.initSession();
      if (isMounted) {
        if (user) {
          setCurrentUser(user);
          await evaluateDeviceBinding(user);
        } else {
          setCurrentScreen("WELCOME");
        }
        setIsInitializing(false);
      }
    }

    init();

    // Session expiration handler
    authStorage.registerAuthExpiredHandler(() => {
      setCurrentUser(null);
      setApprovals([]);
      setSelectedApproval(null);
      setHistoryApprovals([]);
      setReportModalItem(null);
      setComplaintReceipt(null);
      setFeedTab("PENDING");
      setActiveDeviceInfo(null);
      setConflictDevice(null);
      setLinkedAccounts([]);
      setDiscoveredAccounts([]);
      setCurrentScreen("LOGIN");
      Alert.alert(
        "Session Expired",
        "Your PayShield authorization session has expired. Please sign in again."
      );
    });

    // 1-second interval for countdown tickers
    const ticker = setInterval(() => {
      setClockTick((t) => t + 1);
    }, 1000);

    return () => {
      isMounted = false;
      clearInterval(ticker);
      if (cooldownTimerRef.current) clearInterval(cooldownTimerRef.current);
    };
  }, []);

  // Real-time automatic polling every 3 seconds while on DASHBOARD
  useEffect(() => {
    if (currentUser && currentScreen === "DASHBOARD") {
      fetchApprovals(false);
      fetchHistoryApprovals(true);
      loadLinkedAccounts();

      // Register device push token with backend for real-time alerts
      registerForPushNotificationsAsync().then((token) => {
        if (token) {
          api.updatePushToken(token).catch((err) => {
            console.warn("Could not register push token with backend:", err);
          });
        }
      });

      const pollTimer = setInterval(() => {
        fetchApprovals(true); // silent background fetch
        if (feedTab === "HISTORY") {
          fetchHistoryApprovals(true);
        }
      }, 3000);

      return () => clearInterval(pollTimer);
    }
  }, [currentUser, currentScreen, feedTab]);

  // Push notification interactions
  useEffect(() => {
    // Handle cold start when app was launched by tapping a notification
    Notifications.getLastNotificationResponseAsync().then((response) => {
      if (response) {
        const data = response.notification.request.content.data as Record<string, any>;
        if (data && data.approval_id) {
          const approvalId = parseInt(String(data.approval_id), 10);
          if (!isNaN(approvalId)) {
            fetchApprovals(false, approvalId);
          }
        }
      }
    });

    const responseSub = Notifications.addNotificationResponseReceivedListener((response) => {
      const data = response.notification.request.content.data as Record<string, any>;
      if (data && data.approval_id) {
        const approvalId = parseInt(String(data.approval_id), 10);
        if (!isNaN(approvalId)) {
          fetchApprovals(false, approvalId);
        }
      }
    });

    const receivedSub = Notifications.addNotificationReceivedListener(() => {
      fetchApprovals(true);
    });

    return () => {
      responseSub.remove();
      receivedSub.remove();
    };
  }, []);

  // Start OTP cooldown
  const startResendCooldown = (seconds: number = 30) => {
    setResendCooldown(seconds);
    if (cooldownTimerRef.current) clearInterval(cooldownTimerRef.current);

    cooldownTimerRef.current = setInterval(() => {
      setResendCooldown((prev) => {
        if (prev <= 1) {
          if (cooldownTimerRef.current) clearInterval(cooldownTimerRef.current);
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
  };

  // Helper: Format phone for India display
  const formatPhoneDisplay = (raw: string) => {
    const digits = raw.replace(/\D/g, "");
    if (digits.length === 10) {
      return `+91 ${digits.slice(0, 5)} ${digits.slice(5)}`;
    }
    return raw;
  };

  const getDeviceDisplayName = () => {
    if (Platform.OS === "ios") return "Apple iPhone";
    if (Platform.OS === "android") return "Android Phone";
    return "Web Browser Client";
  };

  // ---------------------------------------------------------------------------
  // DEVICE BINDING EVALUATION
  // ---------------------------------------------------------------------------

  const evaluateDeviceBinding = async (user: PayShieldUserProfile) => {
    setDeviceLoading(true);
    try {
      const statusRes = await api.getDeviceStatus();
      const currentDeviceId = authStorage.getDeviceId();
      const platformName = Platform.OS === "ios" ? "IOS" : Platform.OS === "web" ? "WEB" : "ANDROID";
      const devName = getDeviceDisplayName();

      if (!statusRes.has_active_device) {
        // No active device exists on account: register this device automatically
        const regRes = await api.registerDevice(currentDeviceId, devName, platformName, "1.0.0");
        setActiveDeviceInfo(regRes.device);
        setConflictDevice(null);
        setCurrentScreen("DASHBOARD");
      } else if (statusRes.is_current_device_registered) {
        // Current device is already the active registered device
        setActiveDeviceInfo(statusRes.active_device);
        setConflictDevice(null);
        setCurrentScreen("DASHBOARD");
      } else {
        // Another phone is registered on this account! Require replacement
        setConflictDevice(statusRes.active_device);
        setActiveDeviceInfo(null);
        setCurrentScreen("DEVICE_REPLACEMENT");
      }
    } catch (err: any) {
      if (err.code === "DEVICE_REPLACEMENT_REQUIRED") {
        setConflictDevice(err.data?.registered_device || null);
        setActiveDeviceInfo(null);
        setCurrentScreen("DEVICE_REPLACEMENT");
      } else {
        setCurrentScreen("DASHBOARD");
      }
    } finally {
      setDeviceLoading(false);
    }
  };

  // ---------------------------------------------------------------------------
  // BANK ACCOUNT DISCOVERY & 1-TAP LINKING (UPI ONBOARDING)
  // ---------------------------------------------------------------------------

  const loadLinkedAccounts = async () => {
    try {
      const list = await api.fetchLinkedAccounts();
      setLinkedAccounts(list);
    } catch (err) {
      console.log("Error loading linked accounts:", err);
    }
  };

  const openBankDiscoveryModal = async () => {
    setShowBankModal(true);
    setLoadingBankAccounts(true);
    try {
      await loadLinkedAccounts();
      const res = await api.discoverBankAccounts();
      setDiscoveredAccounts(res.accounts || []);
    } catch (err: any) {
      Alert.alert(
        "Bank Search Error",
        err.message || "Could not query partner banks for your mobile number."
      );
    } finally {
      setLoadingBankAccounts(false);
    }
  };

  const handleLinkAccount = async (acc: DiscoveredAccount) => {
    setLinkingAccountId(acc.bank_account_id);
    try {
      const res = await api.linkDiscoveredAccount(acc.account_number, acc.bank_account_id);
      Alert.alert(
        "Bank Account Linked! ✓",
        `${acc.bank_name} (${acc.account_number_masked}) is now active. All future payments from this account will require your explicit mobile authorization.`
      );
      // Refresh both lists
      await loadLinkedAccounts();
      const disc = await api.discoverBankAccounts();
      setDiscoveredAccounts(disc.accounts || []);
      // Update current user linked count
      if (currentUser) {
        setCurrentUser({
          ...currentUser,
          linked_accounts_count: (currentUser.linked_accounts_count || 0) + 1,
        });
      }
    } catch (err: any) {
      Alert.alert("Link Failed", err.message || "Failed to link bank account.");
    } finally {
      setLinkingAccountId(null);
    }
  };

  // ---------------------------------------------------------------------------
  // DEVICE REPLACEMENT FLOW
  // ---------------------------------------------------------------------------

  const handleRequestReplacementOtp = async () => {
    setDeviceLoading(true);
    try {
      const res = await api.requestDeviceReplacementOtp();
      setReplacementOtpSent(true);
      setReplacementDevOtp(res.dev_otp || null);
      startResendCooldown(30);
      Alert.alert(
        "Verification Code Sent",
        `A 6-digit replacement authorization code has been sent to ${formatPhoneDisplay(
          currentUser?.phone_number || ""
        )}.`
      );
    } catch (err: any) {
      Alert.alert("Request Failed", err.message || "Could not send replacement code.");
    } finally {
      setDeviceLoading(false);
    }
  };

  const handleConfirmReplacement = async () => {
    const cleanedOtp = replacementOtpInput.trim().replace(/\D/g, "");
    if (cleanedOtp.length !== 6) {
      Alert.alert("Invalid Code", "Please enter the 6-digit verification code.");
      return;
    }

    setDeviceLoading(true);
    try {
      const currentDeviceId = authStorage.getDeviceId();
      const platformName = Platform.OS === "ios" ? "IOS" : Platform.OS === "web" ? "WEB" : "ANDROID";
      const devName = getDeviceDisplayName();

      const res = await api.replaceDevice(
        cleanedOtp,
        currentDeviceId,
        devName,
        platformName,
        "1.0.0"
      );

      setActiveDeviceInfo(res.device);
      setConflictDevice(null);
      setReplacementOtpSent(false);
      setReplacementOtpInput("");
      setReplacementDevOtp(null);

      Alert.alert(
        "Device Replacement Confirmed ✓",
        "This device is now the sole active device authorized for your PayShield account. Previous device sessions have been revoked."
      );
      setCurrentScreen("DASHBOARD");
    } catch (err: any) {
      Alert.alert("Replacement Failed", err.message || "Invalid or expired code.");
    } finally {
      setDeviceLoading(false);
    }
  };

  const handleRevokeDevice = async () => {
    Alert.alert(
      "Revoke This Device?",
      "Revoking this device will immediately disable payment approvals on this phone. You will need to complete device replacement to re-authorize it.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Revoke Device",
          style: "destructive",
          onPress: async () => {
            setDeviceLoading(true);
            try {
              await api.revokeDevice(activeDeviceInfo?.device_id);
              setShowDeviceModal(false);
              authStorage.clearSession();
              setCurrentUser(null);
              setActiveDeviceInfo(null);
              setApprovals([]);
              setSelectedApproval(null);
              setCurrentScreen("WELCOME");
              Alert.alert(
                "Device Revoked",
                "Your device has been revoked and its session closed."
              );
            } catch (err: any) {
              Alert.alert("Revocation Failed", err.message || "Could not revoke device.");
            } finally {
              setDeviceLoading(false);
            }
          },
        },
      ]
    );
  };

  // ---------------------------------------------------------------------------
  // AUTHENTICATION HANDLERS
  // ---------------------------------------------------------------------------

  const handleInitiateLogin = async () => {
    const cleaned = phoneInput.trim().replace(/\D/g, "");
    if (!cleaned || cleaned.length < 10) {
      Alert.alert("Invalid Mobile Number", "Please enter a valid 10-digit mobile number.");
      return;
    }

    setAuthLoading(true);
    try {
      const res = await api.requestLoginOtp(cleaned);
      setAuthOrigin("LOGIN");
      setDevOtpHint(res.dev_otp || null);
      startResendCooldown(30);
      setCurrentScreen("VERIFY_OTP");
    } catch (err: any) {
      if (err.code === "USER_NOT_FOUND") {
        Alert.alert(
          "Account Not Found",
          "No registered account was found for this mobile number. Please create an account first.",
          [
            { text: "Cancel", style: "cancel" },
            {
              text: "Create Account",
              style: "default",
              onPress: () => {
                setCurrentScreen("REGISTER");
              },
            },
          ]
        );
      } else {
        Alert.alert("Login Failed", err.message || "Failed to send verification code.");
      }
    } finally {
      setAuthLoading(false);
    }
  };

  const handleInitiateRegister = async () => {
    const cleanedName = fullNameInput.trim();
    const cleanedPhone = phoneInput.trim().replace(/\D/g, "");

    if (cleanedName.length < 2) {
      Alert.alert("Name Required", "Please enter your full legal name (at least 2 characters).");
      return;
    }
    if (!cleanedPhone || cleanedPhone.length < 10) {
      Alert.alert("Invalid Mobile Number", "Please enter a valid 10-digit mobile number.");
      return;
    }
    if (!consentAgreed) {
      Alert.alert(
        "Consent Required",
        "Please review and agree to the Terms of Service and Cybersecurity Authorization Policy."
      );
      return;
    }

    setAuthLoading(true);
    try {
      const res = await api.register(cleanedName, cleanedPhone);
      setAuthOrigin("REGISTER");
      setDevOtpHint(res.dev_otp || null);
      startResendCooldown(30);
      setCurrentScreen("VERIFY_OTP");
    } catch (err: any) {
      if (err.code === "ACCOUNT_EXISTS") {
        Alert.alert(
          "Account Already Exists",
          "An account with this mobile number is already registered. Please sign in instead.",
          [
            { text: "Cancel", style: "cancel" },
            {
              text: "Sign In",
              style: "default",
              onPress: () => {
                setCurrentScreen("LOGIN");
              },
            },
          ]
        );
      } else {
        Alert.alert("Registration Failed", err.message || "Could not register account.");
      }
    } finally {
      setAuthLoading(false);
    }
  };

  const handleResendOtp = async () => {
    if (resendCooldown > 0) return;
    const cleanedPhone = phoneInput.trim().replace(/\D/g, "");

    setAuthLoading(true);
    try {
      let res;
      if (authOrigin === "REGISTER") {
        res = await api.register(fullNameInput, cleanedPhone);
      } else {
        res = await api.requestLoginOtp(cleanedPhone);
      }
      setDevOtpHint(res.dev_otp || null);
      startResendCooldown(30);
      Alert.alert("Code Resent", "A fresh 6-digit verification code has been sent.");
    } catch (err: any) {
      Alert.alert("Resend Failed", err.message || "Could not resend verification code.");
    } finally {
      setAuthLoading(false);
    }
  };

  const handleVerifyOtp = async () => {
    const cleanedOtp = otpInput.trim().replace(/\D/g, "");
    if (cleanedOtp.length !== 6) {
      Alert.alert("Invalid Code", "Please enter the complete 6-digit verification code.");
      return;
    }
    const cleanedPhone = phoneInput.trim().replace(/\D/g, "");

    setAuthLoading(true);
    try {
      const res = await api.verifyLoginOtp(cleanedPhone, cleanedOtp);
      setCurrentUser(res.user);
      setOtpInput("");
      setDevOtpHint(null);
      // Immediately evaluate device binding for this authenticated user
      await evaluateDeviceBinding(res.user);
    } catch (err: any) {
      if (err.code === "USER_NOT_FOUND") {
        Alert.alert(
          "Account Not Found",
          "No registered account was found for this mobile number. Please create an account first.",
          [{ text: "OK", onPress: () => setCurrentScreen("REGISTER") }]
        );
      } else {
        Alert.alert("Verification Failed", err.message || "Invalid or expired code.");
      }
    } finally {
      setAuthLoading(false);
    }
  };

  const handleLogout = async () => {
    Alert.alert(
      "Sign Out",
      "Are you sure you want to sign out of PayShield? Your device remains bound to your account for quick sign-in.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Sign Out",
          style: "destructive",
          onPress: async () => {
            await api.logout();
            notifiedApprovalsRef.current.clear();
            setCurrentUser(null);
            setApprovals([]);
            setSelectedApproval(null);
            setHistoryApprovals([]);
            setReportModalItem(null);
            setComplaintReceipt(null);
            setFeedTab("PENDING");
            setActiveDeviceInfo(null);
            setConflictDevice(null);
            setLinkedAccounts([]);
            setDiscoveredAccounts([]);
            setPhoneInput("");
            setFullNameInput("");
            setOtpInput("");
            setDevOtpHint(null);
            setConsentAgreed(false);
            setCurrentScreen("WELCOME");
          },
        },
      ]
    );
  };

  // ---------------------------------------------------------------------------
  // APPROVALS & DECISIONS
  // ---------------------------------------------------------------------------

  const fetchApprovals = async (silent: boolean = false, autoSelectId?: number) => {
    if (!authStorage.isAuthenticated()) return;
    if (!silent) setLoadingApprovals(true);
    try {
      const data = await api.fetchPendingApprovals();
      setApprovals(data);

      if (autoSelectId) {
        const target = data.find((a) => a.id === autoSelectId);
        if (target) {
          notifiedApprovalsRef.current.add(target.id);
          setSelectedApproval(target);
        }
      } else if (selectedApproval) {
        const updated = data.find((a) => a.id === selectedApproval.id);
        if (updated) setSelectedApproval(updated);
      } else {
        // If an approval is pending and not yet shown, automatically select it directly on screen
        const pendingItem = data.find(
          (a) => a.status === "PENDING" && getRemainingSeconds(a.expires_at) > 0
        );
        if (pendingItem && !notifiedApprovalsRef.current.has(pendingItem.id)) {
          notifiedApprovalsRef.current.add(pendingItem.id);
          setSelectedApproval(pendingItem);
        }
      }
    } catch (err: any) {
      if (err.code === "DEVICE_REVOKED") {
        Alert.alert(
          "Device Revoked",
          "This device was revoked. Please complete device replacement to re-authorize it."
        );
        setCurrentScreen("DEVICE_REPLACEMENT");
      }
    } finally {
      if (!silent) setLoadingApprovals(false);
    }
  };

  const getRemainingSeconds = (expiresAt: string) => {
    const diff = Math.floor((new Date(expiresAt).getTime() - Date.now()) / 1000);
    return Math.max(diff, 0);
  };

  const handleDecide = async (approval: ApprovalItem, decision: "APPROVED" | "DENIED") => {
    if (decidingId !== null) return;

    const remaining = getRemainingSeconds(approval.expires_at);
    if (remaining <= 0 || approval.status !== "PENDING") {
      Alert.alert("Request Expired", "This transaction authorization window has expired.");
      await fetchApprovals();
      return;
    }

    const actionText = decision === "APPROVED" ? "Approve" : "Deny";
    const alertMessage =
      decision === "APPROVED"
        ? `Are you sure you want to APPROVE payment of ₹${approval.amount} to ${
            approval.recipient_name || "merchant"
          }? This will instruct the bank to release the funds.`
        : `Are you sure you want to DENY payment of ₹${approval.amount}? This will instruct the bank to cancel the transaction.`;

    Alert.alert(
      `${actionText} Payment?`,
      alertMessage,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: actionText,
          style: decision === "DENIED" ? "destructive" : "default",
          onPress: async () => {
            setDecidingId(approval.id);
            try {
              const res = await api.decideApproval(approval.id, decision);
              setSelectedApproval(null);
              await fetchApprovals();
              await fetchHistoryApprovals(true);

              if (decision === "DENIED") {
                Alert.alert(
                  "Payment Denied ✕",
                  `${res.message || "Payment cancelled."}\n\nWould you like to report this suspicious scam/fraud attempt to the National Cyber Crime Cell (1930)?`,
                  [
                    { text: "Not Now", style: "cancel" },
                    {
                      text: "Report Scam 🚨",
                      style: "destructive",
                      onPress: () => {
                        handleOpenReportModal(approval);
                      },
                    },
                  ]
                );
              } else {
                Alert.alert("Payment Approved ✓", res.message || "Decision processed successfully.");
              }
            } catch (err: any) {
              if (err.code === "DEVICE_REVOKED") {
                Alert.alert(
                  "Device Revoked",
                  "This device was revoked from the account. Device replacement is required."
                );
                setCurrentScreen("DEVICE_REPLACEMENT");
              } else {
                Alert.alert("Decision Error", err.message || "Could not complete decision.");
                await fetchApprovals();
              }
            } finally {
              setDecidingId(null);
            }
          },
        },
      ]
    );
  };

  const fetchHistoryApprovals = async (silent: boolean = false) => {
    if (!authStorage.isAuthenticated()) return;
    if (!silent) setLoadingHistory(true);
    try {
      const data = await api.fetchApprovalHistory();
      setHistoryApprovals(data);
    } catch (err) {
      console.log("Error loading transaction history:", err);
    } finally {
      if (!silent) setLoadingHistory(false);
    }
  };

  const handleOpenReportModal = (item: ApprovalItem) => {
    setReportModalItem(item);
    setScamCategory("PHISHING_FAKE_LINK");
    setScamNotes("");
  };

  const handleSubmitReport = async () => {
    if (!reportModalItem) return;
    setSubmittingReport(true);
    try {
      const res = await api.reportCyberCrime(
        reportModalItem.id,
        scamCategory,
        scamNotes.trim()
      );

      const updateList = (list: ApprovalItem[]) =>
        list.map((it) =>
          it.id === reportModalItem.id
            ? { ...it, is_reported_fraud: true, fraud_report_id: res.complaint_ref }
            : it
        );

      setApprovals(updateList);
      setHistoryApprovals(updateList);

      if (selectedApproval?.id === reportModalItem.id) {
        setSelectedApproval({
          ...selectedApproval,
          is_reported_fraud: true,
          fraud_report_id: res.complaint_ref,
        });
      }

      setReportModalItem(null);
      setComplaintReceipt(res);
    } catch (err: any) {
      Alert.alert(
        "Report Submission Error",
        err.message || "Could not record fraud report. Please try again."
      );
    } finally {
      setSubmittingReport(false);
    }
  };

  // ---------------------------------------------------------------------------
  // RENDER: SPLASH SCREEN
  // ---------------------------------------------------------------------------

  if (isInitializing) {
    return (
      <SafeAreaView style={styles.splashContainer}>
        <StatusBar barStyle="dark-content" />
        <View style={styles.splashBrand}>
          <View style={styles.brandBadge}>
            <Text style={styles.shieldSymbol}>🛡️</Text>
          </View>
          <Text style={styles.splashTitle}>PayShield</Text>
          <Text style={styles.splashSubtitle}>Zero-Trust Payment Protection</Text>
          <ActivityIndicator size="small" color="#2563EB" style={{ marginTop: 20 }} />
        </View>
      </SafeAreaView>
    );
  }

  // ---------------------------------------------------------------------------
  // SCREEN: DEVICE REPLACEMENT (ONE-ACTIVE-DEVICE ENFORCEMENT)
  // ---------------------------------------------------------------------------
  if (currentScreen === "DEVICE_REPLACEMENT") {
    return (
      <SafeAreaView style={styles.safeArea}>
        <StatusBar barStyle="dark-content" />
        <ScrollView contentContainerStyle={styles.authScrollContent}>
          <View style={styles.conflictHero}>
            <View style={styles.conflictBadge}>
              <Text style={{ fontSize: 36 }}>🔒</Text>
            </View>
            <Text style={styles.conflictTitle}>Device Replacement Required</Text>
            <Text style={styles.conflictSubtitle}>
              For cybersecurity protection, PayShield strictly enforces a{" "}
              <Text style={{ fontWeight: "800", color: "#0F172A" }}>
                single active device policy
              </Text>{" "}
              per account to prevent unauthorized parallel access.
            </Text>
          </View>

          {/* Currently registered device card */}
          <View style={styles.conflictCard}>
            <Text style={styles.conflictCardHeader}>CURRENTLY REGISTERED DEVICE</Text>
            <View style={styles.deviceRow}>
              <Text style={styles.deviceIcon}>📱</Text>
              <View style={{ flex: 1 }}>
                <Text style={styles.deviceName}>
                  {conflictDevice?.device_name || "Registered Mobile Phone"}
                </Text>
                <Text style={styles.deviceMeta}>
                  Platform: {conflictDevice?.platform || "Mobile"} • Status: ACTIVE
                </Text>
              </View>
              <View style={styles.badgeActiveDevice}>
                <Text style={styles.badgeActiveDeviceText}>ACTIVE</Text>
              </View>
            </View>

            <View style={styles.divider} />

            <Text style={styles.replacementNoticeText}>
              To authorize this new phone, you must verify your phone ownership.
              Authorizing will revoke access and invalidate sessions on the previous phone.
            </Text>
          </View>

          {/* Replacement Action Box */}
          <View style={styles.cardContainer}>
            {!replacementOtpSent ? (
              <>
                <Text style={styles.inputLabel}>Registered Mobile Number</Text>
                <View style={styles.verifiedPhoneBox}>
                  <Text style={styles.verifiedPhoneText}>
                    {formatPhoneDisplay(currentUser?.phone_number || "")}
                  </Text>
                  <Text style={styles.verifiedTag}>✓ Verified</Text>
                </View>

                <Pressable
                  style={[styles.primaryButton, deviceLoading && { opacity: 0.7 }]}
                  disabled={deviceLoading}
                  onPress={handleRequestReplacementOtp}
                >
                  {deviceLoading ? (
                    <ActivityIndicator color="#FFFFFF" size="small" />
                  ) : (
                    <Text style={styles.primaryButtonText}>
                      Send Replacement Code to Mobile →
                    </Text>
                  )}
                </Pressable>
              </>
            ) : (
              <>
                {replacementDevOtp && (
                  <View style={styles.devBanner}>
                    <Text style={styles.devBannerTitle}>🛠️ DEV REPLACEMENT CODE</Text>
                    <Text style={styles.devBannerCode}>{replacementDevOtp}</Text>
                    <Text style={styles.devBannerSub}>
                      Exposed in local test mode without live SMS charges.
                    </Text>
                  </View>
                )}

                <Text style={styles.inputLabel}>Enter 6-Digit Replacement Code</Text>
                <TextInput
                  style={styles.otpInputField}
                  placeholder="0 0 0 0 0 0"
                  placeholderTextColor="#CBD5E1"
                  keyboardType="number-pad"
                  maxLength={6}
                  value={replacementOtpInput}
                  onChangeText={setReplacementOtpInput}
                  autoFocus
                  editable={!deviceLoading}
                />

                <Pressable
                  style={[styles.primaryButton, deviceLoading && { opacity: 0.7 }]}
                  disabled={deviceLoading}
                  onPress={handleConfirmReplacement}
                >
                  {deviceLoading ? (
                    <ActivityIndicator color="#FFFFFF" size="small" />
                  ) : (
                    <Text style={styles.primaryButtonText}>
                      Authorize & Bind This Device ✓
                    </Text>
                  )}
                </Pressable>

                <View style={styles.resendContainer}>
                  {resendCooldown > 0 ? (
                    <Text style={styles.cooldownText}>
                      Resend code in{" "}
                      <Text style={{ fontWeight: "700" }}>{resendCooldown}s</Text>
                    </Text>
                  ) : (
                    <Pressable onPress={handleRequestReplacementOtp} disabled={deviceLoading}>
                      <Text style={styles.resendActiveLink}>
                        Didn't receive code? Resend
                      </Text>
                    </Pressable>
                  )}
                </View>
              </>
            )}

            <Pressable
              style={[styles.secondaryOutlineButton, { marginTop: 14 }]}
              onPress={handleLogout}
            >
              <Text style={styles.secondaryOutlineButtonText}>Cancel & Sign Out</Text>
            </Pressable>
          </View>
        </ScrollView>
      </SafeAreaView>
    );
  }

  // ---------------------------------------------------------------------------
  // SCREEN: WELCOME
  // ---------------------------------------------------------------------------
  if (currentScreen === "WELCOME") {
    return (
      <SafeAreaView style={styles.safeArea}>
        <StatusBar barStyle="dark-content" />
        <ScrollView contentContainerStyle={styles.authScrollContent}>
          <View style={styles.welcomeHero}>
            <View style={styles.brandBadgeLarge}>
              <Text style={{ fontSize: 44 }}>🛡️</Text>
            </View>
            <Text style={styles.heroBrandName}>PayShield</Text>
            <Text style={styles.heroTagline}>YOUR MONEY. YOUR EXPLICIT CONTROL.</Text>

            <View style={styles.healthChip}>
              <View
                style={[
                  styles.healthDot,
                  { backgroundColor: backendStatus.includes("✓") ? "#16A34A" : "#D97706" },
                ]}
              />
              <Text style={styles.healthText}>{backendStatus}</Text>
            </View>
          </View>

          <View style={styles.featureBox}>
            <Text style={styles.featureTitle}>Why PayShield?</Text>
            <View style={styles.featureRow}>
              <Text style={styles.featureIcon}>✓</Text>
              <Text style={styles.featureText}>
                Stops OTP theft & phishing scams before funds leave your account.
              </Text>
            </View>
            <View style={styles.featureRow}>
              <Text style={styles.featureIcon}>✓</Text>
              <Text style={styles.featureText}>
                Single-device hardware binding prevents unauthorized parallel access.
              </Text>
            </View>
            <View style={styles.featureRow}>
              <Text style={styles.featureIcon}>✓</Text>
              <Text style={styles.featureText}>
                Explicit out-of-band authorization for every bank transaction.
              </Text>
            </View>
          </View>

          <View style={styles.authActionGroup}>
            <Pressable
              style={styles.primaryButton}
              onPress={() => setCurrentScreen("LOGIN")}
            >
              <Text style={styles.primaryButtonText}>Sign In with Mobile →</Text>
            </Pressable>

            <Pressable
              style={styles.secondaryOutlineButton}
              onPress={() => setCurrentScreen("REGISTER")}
            >
              <Text style={styles.secondaryOutlineButtonText}>Create New Account</Text>
            </Pressable>
          </View>

          <Text style={styles.securityFooterNote}>
            🔒 End-to-end encrypted • Student Cybersecurity Prototype
          </Text>
        </ScrollView>
      </SafeAreaView>
    );
  }

  // ---------------------------------------------------------------------------
  // SCREEN: LOGIN
  // ---------------------------------------------------------------------------
  if (currentScreen === "LOGIN") {
    return (
      <SafeAreaView style={styles.safeArea}>
        <StatusBar barStyle="dark-content" />
        <ScrollView contentContainerStyle={styles.authScrollContent}>
          <Pressable
            style={styles.backButton}
            onPress={() => setCurrentScreen("WELCOME")}
          >
            <Text style={styles.backButtonText}>← Back</Text>
          </Pressable>

          <View style={styles.authHeader}>
            <Text style={styles.authTitle}>Welcome Back</Text>
            <Text style={styles.authSubtitle}>
              Sign in with your registered mobile number to authorize pending payments.
            </Text>
          </View>

          <View style={styles.cardContainer}>
            <Text style={styles.inputLabel}>Mobile Number</Text>
            <View style={styles.phoneInputRow}>
              <View style={styles.countryCodeBox}>
                <Text style={styles.countryCodeText}>🇮🇳 +91</Text>
              </View>
              <TextInput
                style={styles.phoneInputField}
                placeholder="10-digit number"
                placeholderTextColor="#94A3B8"
                keyboardType="phone-pad"
                maxLength={10}
                value={phoneInput}
                onChangeText={setPhoneInput}
                editable={!authLoading}
              />
            </View>

            <Text style={styles.inputHelper}>
              Demo numbers: 9000000001 (Rahul) • 9000000002 (Priya) • Or any 982000XXXX
            </Text>

            <Pressable
              style={[styles.primaryButton, authLoading && { opacity: 0.7 }]}
              disabled={authLoading}
              onPress={handleInitiateLogin}
            >
              {authLoading ? (
                <ActivityIndicator color="#FFFFFF" size="small" />
              ) : (
                <Text style={styles.primaryButtonText}>Send Verification Code →</Text>
              )}
            </Pressable>
          </View>

          <View style={styles.switchAuthRow}>
            <Text style={styles.switchAuthText}>Don't have a PayShield account?</Text>
            <Pressable onPress={() => setCurrentScreen("REGISTER")}>
              <Text style={styles.switchAuthLink}> Create account</Text>
            </Pressable>
          </View>
        </ScrollView>
      </SafeAreaView>
    );
  }

  // ---------------------------------------------------------------------------
  // SCREEN: REGISTER
  // ---------------------------------------------------------------------------
  if (currentScreen === "REGISTER") {
    return (
      <SafeAreaView style={styles.safeArea}>
        <StatusBar barStyle="dark-content" />
        <ScrollView contentContainerStyle={styles.authScrollContent}>
          <Pressable
            style={styles.backButton}
            onPress={() => setCurrentScreen("WELCOME")}
          >
            <Text style={styles.backButtonText}>← Back</Text>
          </Pressable>

          <View style={styles.authHeader}>
            <Text style={styles.authTitle}>Create Account</Text>
            <Text style={styles.authSubtitle}>
              Register your identity to protect your bank accounts from unauthorized transactions.
            </Text>
          </View>

          <View style={styles.cardContainer}>
            <Text style={styles.inputLabel}>Full Legal Name</Text>
            <TextInput
              style={styles.textInputField}
              placeholder="e.g. Arun Kumar"
              placeholderTextColor="#94A3B8"
              value={fullNameInput}
              onChangeText={setFullNameInput}
              editable={!authLoading}
            />

            <Text style={[styles.inputLabel, { marginTop: 14 }]}>Mobile Number</Text>
            <View style={styles.phoneInputRow}>
              <View style={styles.countryCodeBox}>
                <Text style={styles.countryCodeText}>🇮🇳 +91</Text>
              </View>
              <TextInput
                style={styles.phoneInputField}
                placeholder="10-digit number"
                placeholderTextColor="#94A3B8"
                keyboardType="phone-pad"
                maxLength={10}
                value={phoneInput}
                onChangeText={setPhoneInput}
                editable={!authLoading}
              />
            </View>

            <Pressable
              style={styles.consentRow}
              onPress={() => setConsentAgreed(!consentAgreed)}
            >
              <View style={[styles.checkbox, consentAgreed && styles.checkboxActive]}>
                {consentAgreed && <Text style={styles.checkboxCheckmark}>✓</Text>}
              </View>
              <Text style={styles.consentText}>
                I consent to PayShield verifying transactions from my linked bank accounts and agree to the{" "}
                <Text style={{ fontWeight: "700", color: "#2563EB" }}>Terms & Security Policy</Text>.
              </Text>
            </Pressable>

            <Pressable
              style={[
                styles.primaryButton,
                (!consentAgreed || authLoading) && { opacity: 0.6 },
              ]}
              disabled={authLoading}
              onPress={handleInitiateRegister}
            >
              {authLoading ? (
                <ActivityIndicator color="#FFFFFF" size="small" />
              ) : (
                <Text style={styles.primaryButtonText}>Register & Verify Mobile →</Text>
              )}
            </Pressable>
          </View>

          <View style={styles.switchAuthRow}>
            <Text style={styles.switchAuthText}>Already registered?</Text>
            <Pressable onPress={() => setCurrentScreen("LOGIN")}>
              <Text style={styles.switchAuthLink}> Sign in</Text>
            </Pressable>
          </View>
        </ScrollView>
      </SafeAreaView>
    );
  }

  // ---------------------------------------------------------------------------
  // SCREEN: PHONE VERIFICATION (OTP)
  // ---------------------------------------------------------------------------
  if (currentScreen === "VERIFY_OTP") {
    return (
      <SafeAreaView style={styles.safeArea}>
        <StatusBar barStyle="dark-content" />
        <ScrollView contentContainerStyle={styles.authScrollContent}>
          <Pressable
            style={styles.backButton}
            onPress={() => {
              setOtpInput("");
              setDevOtpHint(null);
              setCurrentScreen(authOrigin);
            }}
          >
            <Text style={styles.backButtonText}>← Change Number</Text>
          </Pressable>

          <View style={styles.authHeader}>
            <Text style={styles.authTitle}>Verify Mobile Number</Text>
            <Text style={styles.authSubtitle}>
              Enter the 6-digit verification code sent to{"\n"}
              <Text style={{ fontWeight: "800", color: "#0F172A" }}>
                {formatPhoneDisplay(phoneInput)}
              </Text>
            </Text>
          </View>

          {devOtpHint && (
            <View style={styles.devBanner}>
              <Text style={styles.devBannerTitle}>🛠️ DEV / TEST OTP</Text>
              <Text style={styles.devBannerCode}>{devOtpHint}</Text>
              <Text style={styles.devBannerSub}>
                Automatically exposed in local DEBUG mode for testing without SMS charges.
              </Text>
            </View>
          )}

          <View style={styles.cardContainer}>
            <Text style={styles.inputLabel}>6-Digit Verification Code</Text>
            <TextInput
              style={styles.otpInputField}
              placeholder="0 0 0 0 0 0"
              placeholderTextColor="#CBD5E1"
              keyboardType="number-pad"
              maxLength={6}
              value={otpInput}
              onChangeText={setOtpInput}
              autoFocus
              editable={!authLoading}
            />

            <Pressable
              style={[styles.primaryButton, authLoading && { opacity: 0.7 }]}
              disabled={authLoading}
              onPress={handleVerifyOtp}
            >
              {authLoading ? (
                <ActivityIndicator color="#FFFFFF" size="small" />
              ) : (
                <Text style={styles.primaryButtonText}>Verify & Continue ✓</Text>
              )}
            </Pressable>

            <View style={styles.resendContainer}>
              {resendCooldown > 0 ? (
                <Text style={styles.cooldownText}>
                  Resend code in <Text style={{ fontWeight: "700" }}>{resendCooldown}s</Text>
                </Text>
              ) : (
                <Pressable onPress={handleResendOtp} disabled={authLoading}>
                  <Text style={styles.resendActiveLink}>Didn't receive code? Resend OTP</Text>
                </Pressable>
              )}
            </View>
          </View>
        </ScrollView>
      </SafeAreaView>
    );
  }

  // ---------------------------------------------------------------------------
  // SCREEN: AUTHENTICATED DASHBOARD
  // ---------------------------------------------------------------------------
  return (
    <SafeAreaView style={styles.safeArea}>
      <StatusBar barStyle="dark-content" />

      {/* Top Navigation Bar */}
      <View style={styles.topBar}>
        <View style={styles.brandRow}>
          <View style={styles.smallLogo}>
            <Text style={{ fontSize: 16 }}>🛡️</Text>
          </View>
          <View>
            <Text style={styles.topBarBrand}>PayShield</Text>
            <Text style={styles.topBarSub}>PROTECTION ACTIVE</Text>
          </View>
        </View>

        <View style={{ flexDirection: "row", gap: 8 }}>
          <Pressable
            style={styles.deviceManageBtn}
            onPress={() => setShowDeviceModal(true)}
          >
            <Text style={styles.deviceManageText}>📱 Device</Text>
          </Pressable>

          <Pressable style={styles.signOutButton} onPress={handleLogout}>
            <Text style={styles.signOutText}>Sign Out</Text>
          </Pressable>
        </View>
      </View>

      <ScrollView
        style={styles.mainScrollView}
        contentContainerStyle={styles.mainScrollContent}
        showsVerticalScrollIndicator={false}
      >
        {/* User Identity Card */}
        <View style={styles.userProfileCard}>
          <View style={styles.avatarCircle}>
            <Text style={styles.avatarLetter}>
              {currentUser?.full_name ? currentUser.full_name[0].toUpperCase() : "U"}
            </Text>
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.userName}>
              {currentUser?.full_name || "PayShield Customer"}
            </Text>
            <Text style={styles.userPhone}>
              {formatPhoneDisplay(currentUser?.phone_number || "")}
            </Text>
          </View>
          <View style={styles.badgeVerified}>
            <Text style={styles.badgeVerifiedText}>VERIFIED</Text>
          </View>
        </View>

        {/* Bank Accounts UPI Discovery Chip */}
        <Pressable
          style={styles.bankChip}
          onPress={openBankDiscoveryModal}
        >
          <Text style={styles.bankChipIcon}>🏦</Text>
          <View style={{ flex: 1 }}>
            <Text style={styles.bankChipTitle}>
              Linked Bank Accounts ({linkedAccounts.length})
            </Text>
            <Text style={styles.bankChipSub}>
              {linkedAccounts.length > 0
                ? `${linkedAccounts[0].bank_name} •••• ${linkedAccounts[0].account_number_masked.slice(-4)}`
                : "Tap to discover & link accounts via UPI search"}
            </Text>
          </View>
          <View style={styles.bankChipAction}>
            <Text style={styles.bankChipActionText}>+ LINK BANK</Text>
          </View>
        </Pressable>

        {/* Device Binding Chip */}
        <Pressable
          style={styles.deviceChip}
          onPress={() => setShowDeviceModal(true)}
        >
          <Text style={styles.deviceChipIcon}>📱</Text>
          <View style={{ flex: 1 }}>
            <Text style={styles.deviceChipTitle}>
              {activeDeviceInfo?.device_name || getDeviceDisplayName()}
            </Text>
            <Text style={styles.deviceChipSub}>
              Sole Authorized Hardware • Bound to this phone
            </Text>
          </View>
          <Text style={styles.deviceChipTag}>ACTIVE ✓</Text>
        </Pressable>

        {/* Security Shield Banner */}
        <View style={styles.protectionBanner}>
          <Text style={styles.bannerIcon}>🔒</Text>
          <View style={{ flex: 1, marginLeft: 10 }}>
            <Text style={styles.bannerTitle}>Zero-Trust Payment Filter Active</Text>
            <Text style={styles.bannerText}>
              Transactions from your linked bank accounts require explicit authorization from this verified device before funds leave your account.
            </Text>
          </View>
        </View>

        {/* Quick Vibration & Alert System Test */}
        <Pressable
          style={styles.testAlertButton}
          onPress={async () => {
            try {
              // 1. Hardware vibration buzz
              Vibration.vibrate([0, 500, 200, 500, 200, 500]);

              // 2. High-priority OS Notification Banner
              await Notifications.scheduleNotificationAsync({
                content: {
                  title: "🛡️ PayShield Alert Active!",
                  body: "Phone buzz and notification alerts are fully functional on your device.",
                  sound: "default",
                  vibrate: [0, 500, 200, 500, 200, 500],
                  priority: Notifications.AndroidNotificationPriority.MAX,
                },
                trigger: { channelId: "payshield-approvals" },
              });

              Alert.alert(
                "Phone Buzz Active! 🔔",
                "Your phone vibrated and scheduled an alert banner. The real-time warning system is 100% armed."
              );
            } catch (err: any) {
              Alert.alert("Alert Test", err.message || "Could not trigger alert");
            }
          }}
        >
          <Text style={styles.testAlertIcon}>🔔</Text>
          <View style={{ flex: 1 }}>
            <Text style={styles.testAlertTitle}>Test Vibration & Alert</Text>
            <Text style={styles.testAlertSub}>Tap to verify sound, vibration & banner</Text>
          </View>
          <View style={styles.testAlertBadge}>
            <Text style={styles.testAlertBadgeText}>TEST BUZZ</Text>
          </View>
        </Pressable>

        {/* Feed Tab Selector (Pending vs History) */}
        <View style={styles.tabContainer}>
          <Pressable
            style={[styles.tabButton, feedTab === "PENDING" && styles.tabButtonActive]}
            onPress={() => {
              setFeedTab("PENDING");
              fetchApprovals(false);
            }}
          >
            <Text
              style={[
                styles.tabButtonText,
                feedTab === "PENDING" && styles.tabButtonTextActive,
              ]}
            >
              ⏳ Pending ({approvals.filter((a) => a.status === "PENDING").length})
            </Text>
          </Pressable>

          <Pressable
            style={[styles.tabButton, feedTab === "HISTORY" && styles.tabButtonActive]}
            onPress={() => {
              setFeedTab("HISTORY");
              fetchHistoryApprovals(false);
            }}
          >
            <Text
              style={[
                styles.tabButtonText,
                feedTab === "HISTORY" && styles.tabButtonTextActive,
              ]}
            >
              📜 History ({historyApprovals.length})
            </Text>
          </Pressable>
        </View>

        {/* Approvals & History Feed Header */}
        <View style={styles.feedHeaderRow}>
          <View style={{ flexDirection: "row", alignItems: "center" }}>
            <Text style={styles.feedTitle}>
              {feedTab === "PENDING" ? "Payment Approvals" : "Transaction History"}
            </Text>
            {feedTab === "PENDING" &&
              approvals.filter((a) => a.status === "PENDING").length > 0 && (
                <View style={styles.badgePendingCount}>
                  <Text style={styles.pendingCountText}>
                    {approvals.filter((a) => a.status === "PENDING").length}
                  </Text>
                </View>
              )}
          </View>

          <Pressable
            style={styles.refreshButton}
            onPress={() =>
              feedTab === "PENDING" ? fetchApprovals(false) : fetchHistoryApprovals(false)
            }
            disabled={feedTab === "PENDING" ? loadingApprovals : loadingHistory}
          >
            <Text style={styles.refreshButtonText}>
              {(feedTab === "PENDING" ? loadingApprovals : loadingHistory)
                ? "Refreshing..."
                : "Refresh ↻"}
            </Text>
          </Pressable>
        </View>

        {/* Tab Content: PENDING APPROVALS */}
        {feedTab === "PENDING" && (
          loadingApprovals && approvals.length === 0 ? (
            <View style={styles.loadingBox}>
              <ActivityIndicator size="small" color="#2563EB" />
              <Text style={styles.loadingText}>Fetching payment requests...</Text>
            </View>
          ) : approvals.length === 0 ? (
            <View style={styles.emptyFeedCard}>
              <Text style={{ fontSize: 44, marginBottom: 12 }}>🎉</Text>
              <Text style={styles.emptyFeedTitle}>All Caught Up!</Text>
              <Text style={styles.emptyFeedSubtitle}>
                No pending payment requests right now. When a transaction is verified on Dummy Bank, it will automatically appear here with a 60-second authorization timer.
              </Text>
              <Pressable style={styles.emptyRefreshButton} onPress={() => fetchApprovals(false)}>
                <Text style={styles.emptyRefreshText}>Check for New Payments ↻</Text>
              </Pressable>
            </View>
          ) : (
            approvals.map((item) => {
              const remainingSecs = getRemainingSeconds(item.expires_at);
              const isExpired = remainingSecs <= 0 && item.status === "PENDING";
              const effectiveStatus = isExpired ? "EXPIRED" : item.status;

              return (
                <Pressable
                  key={item.id}
                  style={styles.approvalCard}
                  onPress={() => setSelectedApproval(item)}
                >
                  <View style={styles.cardHeader}>
                    <View style={{ flexDirection: "row", alignItems: "center" }}>
                      <Text style={styles.bankTag}>{item.source_bank || "Dummy Bank"}</Text>
                      {item.transaction_type && (
                        <Text style={styles.typeTag}>{item.transaction_type}</Text>
                      )}
                    </View>

                    <View
                      style={[
                        styles.statusPill,
                        effectiveStatus === "PENDING" && styles.statusPillPending,
                        effectiveStatus === "APPROVED" && styles.statusPillApproved,
                        effectiveStatus === "DENIED" && styles.statusPillDenied,
                        effectiveStatus === "EXPIRED" && styles.statusPillExpired,
                      ]}
                    >
                      <Text
                        style={[
                          styles.statusPillText,
                          effectiveStatus === "PENDING" && styles.statusTextPending,
                          effectiveStatus === "APPROVED" && styles.statusTextApproved,
                          effectiveStatus === "DENIED" && styles.statusTextDenied,
                          effectiveStatus === "EXPIRED" && styles.statusTextExpired,
                        ]}
                      >
                        {effectiveStatus}
                      </Text>
                    </View>
                  </View>

                  <View style={styles.cardBody}>
                    <Text style={styles.amountLabel}>AMOUNT</Text>
                    <Text style={styles.amountValue}>
                      {item.currency || "INR"} ₹{item.amount}
                    </Text>
                    <Text style={styles.recipientRow}>
                      Paying to:{" "}
                      <Text style={{ fontWeight: "700", color: "#0F172A" }}>
                        {item.recipient_name || "Merchant"}
                      </Text>
                    </Text>
                    {item.sender_account_masked && (
                      <Text style={styles.accountRow}>
                        From Account: {item.sender_account_masked}
                      </Text>
                    )}
                  </View>

                  <View style={styles.cardFooter}>
                    {effectiveStatus === "PENDING" ? (
                      <View style={styles.countdownRow}>
                        <Text style={styles.countdownTimer}>⏱️ Expires in {remainingSecs}s</Text>
                      </View>
                    ) : (
                      <Text style={styles.resolvedNote}>
                        Request finalized ({effectiveStatus.toLowerCase()})
                      </Text>
                    )}
                    <Text style={styles.viewDetailsLink}>Review Details →</Text>
                  </View>

                  {effectiveStatus === "PENDING" && (
                    <View style={styles.cardActionRow}>
                      <Pressable
                        style={[styles.actionBtn, styles.btnApprove]}
                        disabled={decidingId !== null}
                        onPress={(e) => {
                          e.stopPropagation?.();
                          handleDecide(item, "APPROVED");
                        }}
                      >
                        <Text style={styles.actionBtnText}>
                          {decidingId === item.id ? "Processing..." : "Approve ✓"}
                        </Text>
                      </Pressable>

                      <Pressable
                        style={[styles.actionBtn, styles.btnDeny]}
                        disabled={decidingId !== null}
                        onPress={(e) => {
                          e.stopPropagation?.();
                          handleDecide(item, "DENIED");
                        }}
                      >
                        <Text style={styles.actionBtnText}>Deny ✕</Text>
                      </Pressable>
                    </View>
                  )}
                </Pressable>
              );
            })
          )
        )}

        {/* Tab Content: TRANSACTION HISTORY */}
        {feedTab === "HISTORY" && (
          loadingHistory && historyApprovals.length === 0 ? (
            <View style={styles.loadingBox}>
              <ActivityIndicator size="small" color="#2563EB" />
              <Text style={styles.loadingText}>Loading transaction history...</Text>
            </View>
          ) : historyApprovals.length === 0 ? (
            <View style={styles.emptyFeedCard}>
              <Text style={{ fontSize: 44, marginBottom: 12 }}>📜</Text>
              <Text style={styles.emptyFeedTitle}>No Transactions Yet</Text>
              <Text style={styles.emptyFeedSubtitle}>
                Your transaction approval history will appear here. Whenever a payment is approved, denied, or expired, a tamper-evident audit record is preserved.
              </Text>
              <Pressable style={styles.emptyRefreshButton} onPress={() => fetchHistoryApprovals(false)}>
                <Text style={styles.emptyRefreshText}>Refresh History ↻</Text>
              </Pressable>
            </View>
          ) : (
            historyApprovals.map((item) => {
              const formattedDate = item.created_at
                ? new Date(item.created_at).toLocaleString("en-IN", {
                    day: "2-digit",
                    month: "short",
                    year: "numeric",
                    hour: "2-digit",
                    minute: "2-digit",
                  })
                : "";

              return (
                <Pressable
                  key={`hist-${item.id}`}
                  style={styles.historyCard}
                  onPress={() => setSelectedApproval(item)}
                >
                  <View style={styles.cardHeader}>
                    <View>
                      <View style={{ flexDirection: "row", alignItems: "center" }}>
                        <Text style={styles.bankTag}>{item.source_bank || "Dummy Bank"}</Text>
                        {item.transaction_type && (
                          <Text style={styles.typeTag}>{item.transaction_type}</Text>
                        )}
                      </View>
                      {formattedDate ? (
                        <Text style={styles.historyDateText}>{formattedDate}</Text>
                      ) : null}
                    </View>

                    <View
                      style={[
                        styles.statusPill,
                        item.status === "PENDING" && styles.statusPillPending,
                        item.status === "APPROVED" && styles.statusPillApproved,
                        item.status === "DENIED" && styles.statusPillDenied,
                        item.status === "EXPIRED" && styles.statusPillExpired,
                      ]}
                    >
                      <Text
                        style={[
                          styles.statusPillText,
                          item.status === "PENDING" && styles.statusTextPending,
                          item.status === "APPROVED" && styles.statusTextApproved,
                          item.status === "DENIED" && styles.statusTextDenied,
                          item.status === "EXPIRED" && styles.statusTextExpired,
                        ]}
                      >
                        {item.status}
                      </Text>
                    </View>
                  </View>

                  <View style={styles.cardBody}>
                    <Text style={styles.amountLabel}>AMOUNT</Text>
                    <Text style={styles.amountValue}>
                      {item.currency || "INR"} ₹{item.amount}
                    </Text>
                    <Text style={styles.recipientRow}>
                      Beneficiary:{" "}
                      <Text style={{ fontWeight: "700", color: "#0F172A" }}>
                        {item.recipient_name || "Merchant"}
                      </Text>
                    </Text>
                    {item.recipient_account_masked ? (
                      <Text style={styles.accountRow}>
                        To Account: {item.recipient_account_masked}
                      </Text>
                    ) : null}
                    {item.sender_account_masked ? (
                      <Text style={styles.accountRow}>
                        From Account: {item.sender_account_masked}
                      </Text>
                    ) : null}
                  </View>

                  {/* Reported Status Banner or Report Scam Button */}
                  {item.is_reported_fraud ? (
                    <View style={styles.reportedBadgeRow}>
                      <Text style={styles.reportedBadgeText}>
                        🚨 REPORTED TO CYBER CELL • {item.fraud_report_id}
                      </Text>
                      <Pressable
                        style={styles.viewComplaintBtn}
                        onPress={(e) => {
                          e.stopPropagation?.();
                          setComplaintReceipt({
                            message: "Transaction previously reported.",
                            complaint_ref: item.fraud_report_id || "",
                            helpline: "1930",
                            portal_url: "https://cybercrime.gov.in",
                            approval_id: item.id,
                            already_reported: true,
                            summary: {
                              amount: item.amount,
                              currency: item.currency,
                              recipient_name: item.recipient_name,
                              scam_category: "Reported Scam",
                            },
                          });
                        }}
                      >
                        <Text style={styles.viewComplaintBtnText}>Ticket 📋</Text>
                      </Pressable>
                    </View>
                  ) : (
                    <Pressable
                      style={styles.reportScamCardBtn}
                      onPress={(e) => {
                        e.stopPropagation?.();
                        handleOpenReportModal(item);
                      }}
                    >
                      <Text style={styles.reportScamCardBtnText}>
                        🚨 Report Scam to Cyber Cell (1930)
                      </Text>
                    </Pressable>
                  )}
                </Pressable>
              );
            })
          )
        )}
      </ScrollView>

      {/* --------------------------------------------------------------------- */}
      {/* BANK ACCOUNT DISCOVERY MODAL (PHONEPE / PAYTM / BHIM STYLE) */}
      {/* --------------------------------------------------------------------- */}
      <Modal
        visible={showBankModal}
        animationType="slide"
        transparent={true}
        onRequestClose={() => setShowBankModal(false)}
      >
        <View style={styles.modalOverlay}>
          <View style={styles.modalContent}>
            <View style={styles.modalHeader}>
              <View>
                <Text style={styles.modalTitle}>Link Bank Accounts</Text>
                <Text style={styles.modalSub}>
                  UPI Discovery for +91 {currentUser?.phone_number}
                </Text>
              </View>
              <Pressable
                style={styles.modalCloseBtn}
                onPress={() => setShowBankModal(false)}
              >
                <Text style={styles.modalCloseText}>✕</Text>
              </Pressable>
            </View>

            <ScrollView style={{ maxHeight: 380 }}>
              {loadingBankAccounts ? (
                <View style={{ padding: 30, alignItems: "center" }}>
                  <ActivityIndicator size="small" color="#2563EB" />
                  <Text style={{ marginTop: 10, fontSize: 13, color: "#64748B" }}>
                    Searching Core Banking Solution for registered accounts...
                  </Text>
                </View>
              ) : discoveredAccounts.length === 0 ? (
                <View style={{ padding: 24, alignItems: "center" }}>
                  <Text style={{ fontSize: 32, marginBottom: 8 }}>🔍</Text>
                  <Text style={{ fontSize: 15, fontWeight: "700", color: "#0F172A" }}>
                    No Accounts Discovered
                  </Text>
                  <Text style={{ fontSize: 12, color: "#64748B", textAlign: "center", marginTop: 4 }}>
                    No bank accounts found registered to +91 {currentUser?.phone_number} on partner banks.
                  </Text>
                </View>
              ) : (
                discoveredAccounts.map((acc) => (
                  <View key={acc.bank_account_id} style={styles.discoveredAccCard}>
                    <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
                      <View style={{ flexDirection: "row", alignItems: "center", flex: 1 }}>
                        <Text style={{ fontSize: 24, marginRight: 10 }}>🏦</Text>
                        <View>
                          <Text style={{ fontSize: 14, fontWeight: "800", color: "#0F172A" }}>
                            {acc.bank_name}
                          </Text>
                          <Text style={{ fontSize: 12, color: "#64748B" }}>
                            {acc.account_type} • {acc.account_number_masked}
                          </Text>
                        </View>
                      </View>

                      {acc.is_already_linked ? (
                        <View style={styles.linkedBadge}>
                          <Text style={styles.linkedBadgeText}>LINKED ✓</Text>
                        </View>
                      ) : (
                        <Pressable
                          style={styles.linkActionBtn}
                          disabled={linkingAccountId === acc.bank_account_id}
                          onPress={() => handleLinkAccount(acc)}
                        >
                          <Text style={styles.linkActionBtnText}>
                            {linkingAccountId === acc.bank_account_id ? "Linking..." : "+ Link"}
                          </Text>
                        </Pressable>
                      )}
                    </View>

                    {acc.balance && (
                      <View style={{ marginTop: 8, paddingTop: 6, borderTopWidth: 1, borderTopColor: "#F1F5F9", flexDirection: "row", justifyContent: "space-between" }}>
                        <Text style={{ fontSize: 11, color: "#94A3B8" }}>Available Balance</Text>
                        <Text style={{ fontSize: 12, fontWeight: "700", color: "#16A34A" }}>
                          ₹{parseFloat(acc.balance).toLocaleString("en-IN")}
                        </Text>
                      </View>
                    )}
                  </View>
                ))
              )}
            </ScrollView>

            <Pressable
              style={styles.modalDismissBtn}
              onPress={() => setShowBankModal(false)}
            >
              <Text style={styles.modalDismissText}>Done</Text>
            </Pressable>
          </View>
        </View>
      </Modal>

      {/* --------------------------------------------------------------------- */}
      {/* DEVICE MANAGEMENT MODAL */}
      {/* --------------------------------------------------------------------- */}
      <Modal
        visible={showDeviceModal}
        animationType="slide"
        transparent={true}
        onRequestClose={() => setShowDeviceModal(false)}
      >
        <View style={styles.modalOverlay}>
          <View style={styles.modalContent}>
            <View style={styles.modalHeader}>
              <View>
                <Text style={styles.modalTitle}>Device Binding Security</Text>
                <Text style={styles.modalSub}>Hardware-Linked Authorization</Text>
              </View>
              <Pressable
                style={styles.modalCloseBtn}
                onPress={() => setShowDeviceModal(false)}
              >
                <Text style={styles.modalCloseText}>✕</Text>
              </Pressable>
            </View>

            <View style={styles.detailTable}>
              <View style={styles.detailRow}>
                <Text style={styles.detailLabel}>Device Name</Text>
                <Text style={styles.detailValue}>
                  {activeDeviceInfo?.device_name || getDeviceDisplayName()}
                </Text>
              </View>
              <View style={styles.detailRow}>
                <Text style={styles.detailLabel}>Platform</Text>
                <Text style={styles.detailValue}>
                  {activeDeviceInfo?.platform || Platform.OS.toUpperCase()}
                </Text>
              </View>
              <View style={styles.detailRow}>
                <Text style={styles.detailLabel}>Device ID</Text>
                <Text style={[styles.detailValue, { fontSize: 11 }]}>
                  {activeDeviceInfo?.device_id || authStorage.getDeviceId()}
                </Text>
              </View>
              <View style={styles.detailRow}>
                <Text style={styles.detailLabel}>Hardware Status</Text>
                <Text style={[styles.detailValue, { color: "#16A34A", fontWeight: "700" }]}>
                  ACTIVE & BOUND
                </Text>
              </View>
            </View>

            <View style={[styles.protectionBanner, { marginTop: 14 }]}>
              <Text style={{ fontSize: 18 }}>💡</Text>
              <Text style={[styles.bannerText, { marginLeft: 8 }]}>
                Only this registered phone can authorize transactions. Changing SIM cards does not affect access.
              </Text>
            </View>

            <Pressable
              style={[styles.secondaryOutlineButton, { borderColor: "#FCA5A5", marginTop: 14 }]}
              onPress={handleRevokeDevice}
              disabled={deviceLoading}
            >
              <Text style={{ color: "#DC2626", fontWeight: "700", fontSize: 14 }}>
                Revoke This Device
              </Text>
            </Pressable>

            <Pressable
              style={styles.modalDismissBtn}
              onPress={() => setShowDeviceModal(false)}
            >
              <Text style={styles.modalDismissText}>Close</Text>
            </Pressable>
          </View>
        </View>
      </Modal>

      {/* --------------------------------------------------------------------- */}
      {/* TRANSACTION DETAIL MODAL */}
      {/* --------------------------------------------------------------------- */}
      <Modal
        visible={selectedApproval !== null}
        animationType="slide"
        transparent={true}
        onRequestClose={() => setSelectedApproval(null)}
      >
        <View style={styles.modalOverlay}>
          <View style={styles.modalContent}>
            {selectedApproval && (
              <>
                <View style={styles.modalHeader}>
                  <View>
                    <Text style={styles.modalTitle}>Payment Authorization</Text>
                    <Text style={styles.modalSub}>
                      Ref: {selectedApproval.transaction_ref?.slice(0, 8)}...
                    </Text>
                  </View>
                  <Pressable
                    style={styles.modalCloseBtn}
                    onPress={() => setSelectedApproval(null)}
                  >
                    <Text style={styles.modalCloseText}>✕</Text>
                  </Pressable>
                </View>

                <ScrollView style={{ maxHeight: 360 }}>
                  <View style={styles.modalAmountBanner}>
                    <Text style={styles.modalAmountText}>
                      ₹{selectedApproval.amount}
                    </Text>
                    <Text style={styles.modalCurrencyText}>
                      {selectedApproval.currency || "INR"}
                    </Text>
                  </View>

                  <View style={styles.detailTable}>
                    <View style={styles.detailRow}>
                      <Text style={styles.detailLabel}>Bank Source</Text>
                      <Text style={styles.detailValue}>
                        {selectedApproval.source_bank || "Dummy Bank"}
                      </Text>
                    </View>

                    <View style={styles.detailRow}>
                      <Text style={styles.detailLabel}>Transfer Method</Text>
                      <Text style={styles.detailValue}>
                        {selectedApproval.transaction_type || "Standard"}
                      </Text>
                    </View>

                    <View style={styles.detailRow}>
                      <Text style={styles.detailLabel}>Debited From</Text>
                      <Text style={styles.detailValue}>
                        {selectedApproval.sender_account_masked || "Linked Account"}
                      </Text>
                    </View>

                    <View style={styles.detailRow}>
                      <Text style={styles.detailLabel}>Sender Name</Text>
                      <Text style={styles.detailValue}>
                        {selectedApproval.sender_name || "You"}
                      </Text>
                    </View>

                    <View style={styles.detailRow}>
                      <Text style={styles.detailLabel}>Beneficiary</Text>
                      <Text style={[styles.detailValue, { fontWeight: "700" }]}>
                        {selectedApproval.recipient_name}
                      </Text>
                    </View>

                    {selectedApproval.recipient_account_masked && (
                      <View style={styles.detailRow}>
                        <Text style={styles.detailLabel}>Recipient Account</Text>
                        <Text style={styles.detailValue}>
                          {selectedApproval.recipient_account_masked}
                        </Text>
                      </View>
                    )}

                    {selectedApproval.description ? (
                      <View style={styles.detailRow}>
                        <Text style={styles.detailLabel}>Payment Note</Text>
                        <Text style={styles.detailValue}>
                          {selectedApproval.description}
                        </Text>
                      </View>
                    ) : null}

                    <View style={styles.detailRow}>
                      <Text style={styles.detailLabel}>Current Status</Text>
                      <Text
                        style={[
                          styles.detailValue,
                          {
                            fontWeight: "700",
                            color:
                              selectedApproval.status === "APPROVED"
                                ? "#16A34A"
                                : selectedApproval.status === "DENIED"
                                ? "#DC2626"
                                : "#D97706",
                          },
                        ]}
                      >
                        {getRemainingSeconds(selectedApproval.expires_at) <= 0 &&
                        selectedApproval.status === "PENDING"
                          ? "EXPIRED"
                          : selectedApproval.status}
                      </Text>
                    </View>
                    {selectedApproval.is_reported_fraud ? (
                      <View style={styles.detailRow}>
                        <Text style={styles.detailLabel}>Cyber Crime Status</Text>
                        <Text
                          style={[
                            styles.detailValue,
                            { fontWeight: "700", color: "#DC2626" },
                          ]}
                        >
                          Reported ({selectedApproval.fraud_report_id})
                        </Text>
                      </View>
                    ) : null}
                  </View>
                </ScrollView>

                {selectedApproval.is_reported_fraud ? (
                  <Pressable
                    style={[styles.modalDismissBtn, { backgroundColor: "#DC2626", marginTop: 12 }]}
                    onPress={() => {
                      const item = selectedApproval;
                      setSelectedApproval(null);
                      setComplaintReceipt({
                        message: "Transaction previously reported.",
                        complaint_ref: item.fraud_report_id || "",
                        helpline: "1930",
                        portal_url: "https://cybercrime.gov.in",
                        approval_id: item.id,
                        already_reported: true,
                        summary: {
                          amount: item.amount,
                          currency: item.currency,
                          recipient_name: item.recipient_name,
                          scam_category: "Reported Scam",
                        },
                      });
                    }}
                  >
                    <Text style={[styles.modalDismissText, { color: "#FFFFFF", fontWeight: "800" }]}>
                      View Cyber Cell Reference 📋
                    </Text>
                  </Pressable>
                ) : !selectedApproval.is_reported_fraud &&
                  (selectedApproval.status === "DENIED" ||
                    selectedApproval.status === "EXPIRED") ? (
                  <Pressable
                    style={[styles.modalDismissBtn, { backgroundColor: "#FFF1F2", borderColor: "#FECDD3", borderWidth: 1, marginTop: 12 }]}
                    onPress={() => {
                      const item = selectedApproval;
                      setSelectedApproval(null);
                      handleOpenReportModal(item);
                    }}
                  >
                    <Text style={[styles.modalDismissText, { color: "#E11D48", fontWeight: "800" }]}>
                      🚨 Report Scam to Cyber Cell (1930)
                    </Text>
                  </Pressable>
                ) : null}

                {selectedApproval.status === "PENDING" &&
                getRemainingSeconds(selectedApproval.expires_at) > 0 ? (
                  <View style={styles.modalActionGroup}>
                    <Pressable
                      style={[styles.modalBtn, styles.btnApprove]}
                      disabled={decidingId !== null}
                      onPress={() => handleDecide(selectedApproval, "APPROVED")}
                    >
                      <Text style={styles.modalBtnText}>
                        {decidingId === selectedApproval.id
                          ? "Processing..."
                          : "Approve Payment ✓"}
                      </Text>
                    </Pressable>

                    <Pressable
                      style={[styles.modalBtn, styles.btnDeny]}
                      disabled={decidingId !== null}
                      onPress={() => handleDecide(selectedApproval, "DENIED")}
                    >
                      <Text style={styles.modalBtnText}>Deny Payment ✕</Text>
                    </Pressable>
                  </View>
                ) : (
                  <Pressable
                    style={styles.modalDismissBtn}
                    onPress={() => setSelectedApproval(null)}
                  >
                    <Text style={styles.modalDismissText}>Close</Text>
                  </Pressable>
                )}
              </>
            )}
          </View>
        </View>
      </Modal>

      {/* --------------------------------------------------------------------- */}
      {/* REPORT SCAM TO CYBER CRIME MODAL (1930 / CYBERCRIME.GOV.IN) */}
      {/* --------------------------------------------------------------------- */}
      <Modal
        visible={reportModalItem !== null}
        animationType="slide"
        transparent={true}
        onRequestClose={() => setReportModalItem(null)}
      >
        <View style={styles.modalOverlay}>
          <View style={[styles.modalContent, { maxHeight: "90%" }]}>
            <View style={styles.modalHeader}>
              <View style={{ flex: 1 }}>
                <Text style={styles.modalTitle}>🚨 Report Scam to Cyber Cell</Text>
                <Text style={styles.modalSub}>
                  National Cyber Crime Portal & 1930 Helpline
                </Text>
              </View>
              <Pressable
                style={styles.modalCloseBtn}
                onPress={() => setReportModalItem(null)}
              >
                <Text style={styles.modalCloseText}>✕</Text>
              </Pressable>
            </View>

            <ScrollView showsVerticalScrollIndicator={false}>
              {reportModalItem && (
                <>
                  <View style={styles.reportSummaryBox}>
                    <Text style={styles.reportSummaryTitle}>Suspect Transaction Details</Text>
                    <View style={styles.detailRow}>
                      <Text style={styles.detailLabel}>Amount</Text>
                      <Text style={[styles.detailValue, { color: "#DC2626", fontWeight: "800" }]}>
                        ₹{reportModalItem.amount}
                      </Text>
                    </View>
                    <View style={styles.detailRow}>
                      <Text style={styles.detailLabel}>Recipient</Text>
                      <Text style={styles.detailValue}>{reportModalItem.recipient_name || "Unknown"}</Text>
                    </View>
                    {reportModalItem.recipient_account_masked ? (
                      <View style={styles.detailRow}>
                        <Text style={styles.detailLabel}>Account</Text>
                        <Text style={styles.detailValue}>{reportModalItem.recipient_account_masked}</Text>
                      </View>
                    ) : null}
                    <View style={styles.detailRow}>
                      <Text style={styles.detailLabel}>Bank Source</Text>
                      <Text style={styles.detailValue}>{reportModalItem.source_bank || "Dummy Bank"}</Text>
                    </View>
                  </View>

                  <Text style={styles.fieldSectionLabel}>Select Scam Category</Text>
                  <View style={styles.categoryContainer}>
                    {SCAM_CATEGORIES.map((cat) => {
                      const isSelected = scamCategory === cat.id;
                      return (
                        <Pressable
                          key={cat.id}
                          style={[
                            styles.categoryChip,
                            isSelected && styles.categoryChipSelected,
                          ]}
                          onPress={() => setScamCategory(cat.id)}
                        >
                          <Text style={styles.categoryIcon}>{cat.icon}</Text>
                          <Text
                            style={[
                              styles.categoryText,
                              isSelected && styles.categoryTextSelected,
                            ]}
                          >
                            {cat.label}
                          </Text>
                        </Pressable>
                      );
                    })}
                  </View>

                  <Text style={styles.fieldSectionLabel}>Additional Notes / Evidence (Optional)</Text>
                  <TextInput
                    style={styles.notesInput}
                    placeholder="e.g. Caller claimed to be Mumbai Police or electricity board..."
                    placeholderTextColor="#94A3B8"
                    multiline={true}
                    numberOfLines={3}
                    value={scamNotes}
                    onChangeText={setScamNotes}
                    maxLength={500}
                  />

                  <View style={styles.cyberHelplineBanner}>
                    <Text style={{ fontSize: 18 }}>🛡️</Text>
                    <View style={{ flex: 1, marginLeft: 8 }}>
                      <Text style={styles.cyberHelplineTitle}>Evidence Preservation</Text>
                      <Text style={styles.cyberHelplineText}>
                        PayShield will cryptographically log this transaction attempt. You will receive an official reference ID to quote when speaking to 1930 Cyber Cell.
                      </Text>
                    </View>
                  </View>

                  <Pressable
                    style={[styles.primaryButton, { backgroundColor: "#DC2626", marginTop: 14 }]}
                    onPress={handleSubmitReport}
                    disabled={submittingReport}
                  >
                    {submittingReport ? (
                      <ActivityIndicator size="small" color="#FFFFFF" />
                    ) : (
                      <Text style={styles.primaryButtonText}>Submit Evidence to Cyber Cell 🚨</Text>
                    )}
                  </Pressable>
                </>
              )}
            </ScrollView>
          </View>
        </View>
      </Modal>

      {/* --------------------------------------------------------------------- */}
      {/* CYBER CRIME COMPLAINT RECEIPT MODAL */}
      {/* --------------------------------------------------------------------- */}
      <Modal
        visible={complaintReceipt !== null}
        animationType="slide"
        transparent={true}
        onRequestClose={() => setComplaintReceipt(null)}
      >
        <View style={styles.modalOverlay}>
          <View style={styles.modalContent}>
            <View style={styles.modalHeader}>
              <View style={{ flex: 1 }}>
                <Text style={styles.modalTitle}>Official Report Acknowledged</Text>
                <Text style={styles.modalSub}>National Cyber Crime Reporting Portal</Text>
              </View>
              <Pressable
                style={styles.modalCloseBtn}
                onPress={() => setComplaintReceipt(null)}
              >
                <Text style={styles.modalCloseText}>✕</Text>
              </Pressable>
            </View>

            <View style={styles.ticketCard}>
              <Text style={styles.ticketLabel}>INCIDENT REFERENCE TICKET</Text>
              <Text style={styles.ticketNumber}>{complaintReceipt?.complaint_ref}</Text>
              <Text style={styles.ticketSub}>
                Logged in PayShield Security Audit Registry
              </Text>
            </View>

            <View style={styles.receiptHelpBox}>
              <Text style={styles.receiptHelpText}>
                ⚠️ Please quote the reference ticket above when reporting to the National Cyber Crime Helpline or visiting the police station.
              </Text>
            </View>

            <View style={{ gap: 10, marginTop: 16 }}>
              <Pressable
                style={[styles.primaryButton, { backgroundColor: "#16A34A" }]}
                onPress={() => Linking.openURL("tel:1930")}
              >
                <Text style={styles.primaryButtonText}>📞 Call 1930 Cyber Helpline</Text>
              </Pressable>

              <Pressable
                style={[styles.primaryButton, { backgroundColor: "#2563EB" }]}
                onPress={() => Linking.openURL("https://cybercrime.gov.in")}
              >
                <Text style={styles.primaryButtonText}>🌐 Open cybercrime.gov.in</Text>
              </Pressable>

              <Pressable
                style={styles.modalDismissBtn}
                onPress={() => setComplaintReceipt(null)}
              >
                <Text style={styles.modalDismissText}>Done</Text>
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

// -----------------------------------------------------------------------------
// STYLES
// -----------------------------------------------------------------------------
const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: "#F8FAFC",
    paddingTop: Platform.OS === "android" ? Math.max(StatusBar.currentHeight || 0, 24) + 6 : 0,
  },
  splashContainer: {
    flex: 1,
    backgroundColor: "#F8FAFC",
    justifyContent: "center",
    alignItems: "center",
  },
  splashBrand: {
    alignItems: "center",
  },
  brandBadge: {
    width: 64,
    height: 64,
    borderRadius: 20,
    backgroundColor: "#EFF6FF",
    justifyContent: "center",
    alignItems: "center",
    marginBottom: 16,
    borderWidth: 1,
    borderColor: "#BFDBFE",
  },
  brandBadgeLarge: {
    width: 80,
    height: 80,
    borderRadius: 24,
    backgroundColor: "#EFF6FF",
    justifyContent: "center",
    alignItems: "center",
    marginBottom: 16,
    borderWidth: 1,
    borderColor: "#BFDBFE",
  },
  shieldSymbol: {
    fontSize: 32,
  },
  splashTitle: {
    fontSize: 28,
    fontWeight: "800",
    color: "#0F172A",
    letterSpacing: -0.5,
  },
  splashSubtitle: {
    fontSize: 14,
    color: "#64748B",
    marginTop: 6,
  },

  // Auth & Welcome Scroll container
  authScrollContent: {
    paddingHorizontal: 24,
    paddingTop: Platform.OS === "android" ? 30 : 16,
    paddingBottom: 40,
  },
  backButton: {
    alignSelf: "flex-start",
    paddingVertical: 8,
    paddingHorizontal: 12,
    borderRadius: 8,
    backgroundColor: "#E2E8F0",
    marginBottom: 16,
  },
  backButtonText: {
    fontSize: 14,
    fontWeight: "600",
    color: "#334155",
  },
  welcomeHero: {
    alignItems: "center",
    paddingVertical: 20,
  },
  heroBrandName: {
    fontSize: 34,
    fontWeight: "900",
    color: "#0F172A",
    letterSpacing: -0.5,
  },
  heroTagline: {
    fontSize: 11,
    fontWeight: "800",
    color: "#2563EB",
    letterSpacing: 1.5,
    marginTop: 6,
  },
  healthChip: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: "#F1F5F9",
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 20,
    marginTop: 14,
  },
  healthDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    marginRight: 8,
  },
  healthText: {
    fontSize: 12,
    fontWeight: "600",
    color: "#475569",
  },
  featureBox: {
    backgroundColor: "#FFFFFF",
    borderRadius: 16,
    padding: 20,
    marginVertical: 20,
    borderWidth: 1,
    borderColor: "#E2E8F0",
  },
  featureTitle: {
    fontSize: 16,
    fontWeight: "700",
    color: "#0F172A",
    marginBottom: 14,
  },
  featureRow: {
    flexDirection: "row",
    alignItems: "flex-start",
    marginBottom: 12,
  },
  featureIcon: {
    fontSize: 14,
    fontWeight: "800",
    color: "#2563EB",
    marginRight: 10,
    marginTop: 2,
  },
  featureText: {
    fontSize: 13,
    color: "#475569",
    flex: 1,
    lineHeight: 18,
  },
  authActionGroup: {
    marginTop: 10,
    gap: 12,
  },
  primaryButton: {
    backgroundColor: "#2563EB",
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: "center",
    justifyContent: "center",
  },
  primaryButtonText: {
    fontSize: 15,
    fontWeight: "700",
    color: "#FFFFFF",
  },
  secondaryOutlineButton: {
    backgroundColor: "transparent",
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 1.5,
    borderColor: "#CBD5E1",
  },
  secondaryOutlineButtonText: {
    fontSize: 15,
    fontWeight: "700",
    color: "#1E293B",
  },
  securityFooterNote: {
    textAlign: "center",
    fontSize: 12,
    color: "#94A3B8",
    marginTop: 24,
  },

  // Auth Header
  authHeader: {
    marginBottom: 20,
  },
  authTitle: {
    fontSize: 26,
    fontWeight: "800",
    color: "#0F172A",
    marginBottom: 6,
  },
  authSubtitle: {
    fontSize: 14,
    color: "#64748B",
    lineHeight: 20,
  },
  cardContainer: {
    backgroundColor: "#FFFFFF",
    borderRadius: 16,
    padding: 20,
    borderWidth: 1,
    borderColor: "#E2E8F0",
  },
  inputLabel: {
    fontSize: 13,
    fontWeight: "700",
    color: "#334155",
    marginBottom: 8,
  },
  inputHelper: {
    fontSize: 11,
    color: "#64748B",
    marginTop: 6,
    marginBottom: 16,
  },
  textInputField: {
    backgroundColor: "#F8FAFC",
    borderWidth: 1,
    borderColor: "#CBD5E1",
    borderRadius: 10,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 15,
    color: "#0F172A",
  },
  phoneInputRow: {
    flexDirection: "row",
    gap: 10,
  },
  countryCodeBox: {
    backgroundColor: "#F1F5F9",
    borderWidth: 1,
    borderColor: "#CBD5E1",
    borderRadius: 10,
    paddingHorizontal: 12,
    justifyContent: "center",
  },
  countryCodeText: {
    fontSize: 14,
    fontWeight: "700",
    color: "#334155",
  },
  phoneInputField: {
    flex: 1,
    backgroundColor: "#F8FAFC",
    borderWidth: 1,
    borderColor: "#CBD5E1",
    borderRadius: 10,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 15,
    color: "#0F172A",
  },
  consentRow: {
    flexDirection: "row",
    alignItems: "flex-start",
    marginTop: 14,
    marginBottom: 20,
  },
  checkbox: {
    width: 20,
    height: 20,
    borderRadius: 4,
    borderWidth: 1.5,
    borderColor: "#94A3B8",
    alignItems: "center",
    justifyContent: "center",
    marginRight: 10,
    marginTop: 2,
    backgroundColor: "#FFFFFF",
  },
  checkboxActive: {
    backgroundColor: "#2563EB",
    borderColor: "#2563EB",
  },
  checkboxCheckmark: {
    color: "#FFFFFF",
    fontSize: 13,
    fontWeight: "900",
  },
  consentText: {
    fontSize: 12,
    color: "#475569",
    flex: 1,
    lineHeight: 18,
  },
  switchAuthRow: {
    flexDirection: "row",
    justifyContent: "center",
    alignItems: "center",
    marginTop: 24,
  },
  switchAuthText: {
    fontSize: 14,
    color: "#64748B",
  },
  switchAuthLink: {
    fontSize: 14,
    fontWeight: "700",
    color: "#2563EB",
  },

  // OTP Verification
  devBanner: {
    backgroundColor: "#FEF3C7",
    borderColor: "#F59E0B",
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    marginBottom: 16,
    alignItems: "center",
  },
  devBannerTitle: {
    fontSize: 12,
    fontWeight: "800",
    color: "#B45309",
    letterSpacing: 1,
  },
  devBannerCode: {
    fontSize: 28,
    fontWeight: "900",
    letterSpacing: 6,
    color: "#92400E",
    marginVertical: 4,
  },
  devBannerSub: {
    fontSize: 11,
    color: "#78350F",
    textAlign: "center",
  },
  otpInputField: {
    backgroundColor: "#F8FAFC",
    borderWidth: 1.5,
    borderColor: "#93C5FD",
    borderRadius: 12,
    paddingVertical: 14,
    fontSize: 24,
    fontWeight: "800",
    textAlign: "center",
    letterSpacing: 8,
    color: "#1E3A8A",
    marginBottom: 16,
  },
  resendContainer: {
    marginTop: 16,
    alignItems: "center",
  },
  cooldownText: {
    fontSize: 13,
    color: "#64748B",
  },
  resendActiveLink: {
    fontSize: 13,
    fontWeight: "700",
    color: "#2563EB",
  },

  // Device Conflict / Replacement Screen
  conflictHero: {
    alignItems: "center",
    paddingVertical: 16,
  },
  conflictBadge: {
    width: 72,
    height: 72,
    borderRadius: 22,
    backgroundColor: "#FEF3C7",
    justifyContent: "center",
    alignItems: "center",
    marginBottom: 14,
    borderWidth: 1,
    borderColor: "#FDE68A",
  },
  conflictTitle: {
    fontSize: 22,
    fontWeight: "900",
    color: "#0F172A",
    textAlign: "center",
  },
  conflictSubtitle: {
    fontSize: 13,
    color: "#64748B",
    textAlign: "center",
    marginTop: 8,
    lineHeight: 18,
  },
  conflictCard: {
    backgroundColor: "#FFFFFF",
    borderRadius: 16,
    padding: 18,
    marginBottom: 16,
    borderWidth: 1,
    borderColor: "#E2E8F0",
  },
  conflictCardHeader: {
    fontSize: 11,
    fontWeight: "800",
    color: "#94A3B8",
    letterSpacing: 0.5,
    marginBottom: 10,
  },
  deviceRow: {
    flexDirection: "row",
    alignItems: "center",
  },
  deviceIcon: {
    fontSize: 24,
    marginRight: 12,
  },
  deviceName: {
    fontSize: 15,
    fontWeight: "800",
    color: "#0F172A",
  },
  deviceMeta: {
    fontSize: 12,
    color: "#64748B",
    marginTop: 2,
  },
  badgeActiveDevice: {
    backgroundColor: "#DCFCE7",
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 6,
  },
  badgeActiveDeviceText: {
    fontSize: 10,
    fontWeight: "800",
    color: "#16A34A",
  },
  divider: {
    height: 1,
    backgroundColor: "#F1F5F9",
    marginVertical: 12,
  },
  replacementNoticeText: {
    fontSize: 12,
    color: "#64748B",
    lineHeight: 16,
  },
  verifiedPhoneBox: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    backgroundColor: "#F8FAFC",
    borderWidth: 1,
    borderColor: "#E2E8F0",
    borderRadius: 10,
    padding: 12,
    marginBottom: 16,
  },
  verifiedPhoneText: {
    fontSize: 15,
    fontWeight: "800",
    color: "#0F172A",
  },
  verifiedTag: {
    fontSize: 11,
    fontWeight: "700",
    color: "#16A34A",
  },

  // Authenticated Top Bar
  topBar: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 20,
    paddingVertical: 12,
    backgroundColor: "#FFFFFF",
    borderBottomWidth: 1,
    borderBottomColor: "#E2E8F0",
  },
  brandRow: {
    flexDirection: "row",
    alignItems: "center",
  },
  smallLogo: {
    width: 32,
    height: 32,
    borderRadius: 8,
    backgroundColor: "#EFF6FF",
    justifyContent: "center",
    alignItems: "center",
    marginRight: 8,
  },
  topBarBrand: {
    fontSize: 16,
    fontWeight: "800",
    color: "#0F172A",
  },
  topBarSub: {
    fontSize: 9,
    fontWeight: "800",
    color: "#16A34A",
    letterSpacing: 0.5,
  },
  deviceManageBtn: {
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 8,
    backgroundColor: "#EFF6FF",
  },
  deviceManageText: {
    fontSize: 12,
    fontWeight: "700",
    color: "#2563EB",
  },
  signOutButton: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 8,
    backgroundColor: "#FEE2E2",
  },
  signOutText: {
    fontSize: 12,
    fontWeight: "700",
    color: "#DC2626",
  },

  mainScrollView: {
    flex: 1,
  },
  mainScrollContent: {
    padding: 16,
    paddingBottom: 40,
  },

  // User Profile Card
  userProfileCard: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: "#FFFFFF",
    borderRadius: 14,
    padding: 14,
    borderWidth: 1,
    borderColor: "#E2E8F0",
    marginBottom: 10,
  },
  avatarCircle: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: "#2563EB",
    justifyContent: "center",
    alignItems: "center",
    marginRight: 12,
  },
  avatarLetter: {
    fontSize: 18,
    fontWeight: "800",
    color: "#FFFFFF",
  },
  userName: {
    fontSize: 16,
    fontWeight: "700",
    color: "#0F172A",
  },
  userPhone: {
    fontSize: 13,
    color: "#64748B",
    marginTop: 2,
  },
  badgeVerified: {
    backgroundColor: "#DCFCE7",
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 6,
  },
  badgeVerifiedText: {
    fontSize: 10,
    fontWeight: "800",
    color: "#16A34A",
  },

  // Bank Discovery Chip (PhonePe/UPI Style)
  bankChip: {
    flexDirection: "row",
    alignItems: "center",
    borderRadius: 12,
    padding: 12,
    borderWidth: 1,
    borderColor: "#BFDBFE",
    backgroundColor: "#F0F7FF",
    marginBottom: 10,
  },
  bankChipIcon: {
    fontSize: 22,
    marginRight: 10,
  },
  bankChipTitle: {
    fontSize: 13,
    fontWeight: "800",
    color: "#1E3A8A",
  },
  bankChipSub: {
    fontSize: 11,
    color: "#3B82F6",
    marginTop: 1,
  },
  bankChipAction: {
    backgroundColor: "#2563EB",
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: 6,
  },
  bankChipActionText: {
    fontSize: 10,
    fontWeight: "800",
    color: "#FFFFFF",
  },

  // Device Chip
  deviceChip: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: "#FFFFFF",
    borderRadius: 12,
    padding: 12,
    borderWidth: 1,
    borderColor: "#E2E8F0",
    marginBottom: 10,
  },
  deviceChipIcon: {
    fontSize: 20,
    marginRight: 10,
  },
  deviceChipTitle: {
    fontSize: 13,
    fontWeight: "700",
    color: "#0F172A",
  },
  deviceChipSub: {
    fontSize: 11,
    color: "#64748B",
    marginTop: 1,
  },
  deviceChipTag: {
    fontSize: 10,
    fontWeight: "800",
    color: "#16A34A",
    backgroundColor: "#DCFCE7",
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 6,
  },

  // Protection Banner
  protectionBanner: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: "#EFF6FF",
    borderRadius: 12,
    padding: 12,
    borderWidth: 1,
    borderColor: "#BFDBFE",
    marginBottom: 16,
  },
  bannerIcon: {
    fontSize: 22,
  },
  bannerTitle: {
    fontSize: 13,
    fontWeight: "700",
    color: "#1E40AF",
  },
  bannerText: {
    fontSize: 11,
    color: "#3B82F6",
    lineHeight: 16,
    marginTop: 2,
  },

  // Test Alert Button
  testAlertButton: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: "#FEF3C7",
    borderRadius: 12,
    padding: 12,
    borderWidth: 1,
    borderColor: "#FDE68A",
    marginBottom: 16,
  },
  testAlertIcon: {
    fontSize: 20,
    marginRight: 10,
  },
  testAlertTitle: {
    fontSize: 13,
    fontWeight: "700",
    color: "#92400E",
  },
  testAlertSub: {
    fontSize: 11,
    color: "#B45309",
    marginTop: 1,
  },
  testAlertBadge: {
    backgroundColor: "#F59E0B",
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 6,
  },
  testAlertBadgeText: {
    fontSize: 10,
    fontWeight: "800",
    color: "#FFFFFF",
  },

  // Feed Section Header
  feedHeaderRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 12,
  },
  feedTitle: {
    fontSize: 18,
    fontWeight: "800",
    color: "#0F172A",
  },
  badgePendingCount: {
    backgroundColor: "#FEF3C7",
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 12,
    marginLeft: 8,
  },
  pendingCountText: {
    fontSize: 12,
    fontWeight: "800",
    color: "#B45309",
  },
  refreshButton: {
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: 6,
    backgroundColor: "#F1F5F9",
  },
  refreshButtonText: {
    fontSize: 12,
    fontWeight: "700",
    color: "#475569",
  },

  loadingBox: {
    padding: 30,
    alignItems: "center",
    justifyContent: "center",
  },
  loadingText: {
    fontSize: 13,
    color: "#64748B",
    marginTop: 8,
  },

  emptyFeedCard: {
    backgroundColor: "#FFFFFF",
    borderRadius: 16,
    padding: 30,
    alignItems: "center",
    borderWidth: 1,
    borderColor: "#E2E8F0",
  },
  emptyFeedTitle: {
    fontSize: 18,
    fontWeight: "800",
    color: "#0F172A",
    marginBottom: 6,
  },
  emptyFeedSubtitle: {
    fontSize: 13,
    color: "#64748B",
    textAlign: "center",
    lineHeight: 18,
    marginBottom: 16,
  },
  emptyRefreshButton: {
    backgroundColor: "#EFF6FF",
    paddingHorizontal: 16,
    paddingVertical: 10,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: "#BFDBFE",
  },
  emptyRefreshText: {
    fontSize: 13,
    fontWeight: "700",
    color: "#2563EB",
  },

  // Approval Card
  approvalCard: {
    backgroundColor: "#FFFFFF",
    borderRadius: 16,
    padding: 16,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: "#E2E8F0",
  },
  cardHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 10,
  },
  bankTag: {
    fontSize: 12,
    fontWeight: "800",
    color: "#0F172A",
    marginRight: 6,
  },
  typeTag: {
    fontSize: 10,
    fontWeight: "700",
    color: "#475569",
    backgroundColor: "#F1F5F9",
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
  },
  statusPill: {
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 6,
  },
  statusPillPending: {
    backgroundColor: "#FEF3C7",
  },
  statusPillApproved: {
    backgroundColor: "#DCFCE7",
  },
  statusPillDenied: {
    backgroundColor: "#FEE2E2",
  },
  statusPillExpired: {
    backgroundColor: "#F1F5F9",
  },
  statusPillText: {
    fontSize: 10,
    fontWeight: "800",
  },
  statusTextPending: {
    color: "#B45309",
  },
  statusTextApproved: {
    color: "#16A34A",
  },
  statusTextDenied: {
    color: "#DC2626",
  },
  statusTextExpired: {
    color: "#64748B",
  },

  cardBody: {
    marginVertical: 4,
  },
  amountLabel: {
    fontSize: 10,
    fontWeight: "800",
    color: "#94A3B8",
    letterSpacing: 0.5,
  },
  amountValue: {
    fontSize: 24,
    fontWeight: "900",
    color: "#0F172A",
    marginVertical: 2,
  },
  recipientRow: {
    fontSize: 13,
    color: "#475569",
    marginTop: 2,
  },
  accountRow: {
    fontSize: 12,
    color: "#64748B",
    marginTop: 2,
  },

  cardFooter: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginTop: 12,
    paddingTop: 10,
    borderTopWidth: 1,
    borderTopColor: "#F1F5F9",
  },
  countdownRow: {
    flexDirection: "row",
    alignItems: "center",
  },
  countdownTimer: {
    fontSize: 12,
    fontWeight: "700",
    color: "#D97706",
  },
  resolvedNote: {
    fontSize: 11,
    color: "#94A3B8",
    fontStyle: "italic",
  },
  viewDetailsLink: {
    fontSize: 12,
    fontWeight: "700",
    color: "#2563EB",
  },

  cardActionRow: {
    flexDirection: "row",
    gap: 10,
    marginTop: 12,
  },
  actionBtn: {
    flex: 1,
    paddingVertical: 10,
    borderRadius: 8,
    alignItems: "center",
    justifyContent: "center",
  },
  btnApprove: {
    backgroundColor: "#16A34A",
  },
  btnDeny: {
    backgroundColor: "#DC2626",
  },
  actionBtnText: {
    fontSize: 13,
    fontWeight: "800",
    color: "#FFFFFF",
  },

  // Modal Styles
  modalOverlay: {
    flex: 1,
    backgroundColor: "rgba(15, 23, 42, 0.6)",
    justifyContent: "flex-end",
  },
  modalContent: {
    backgroundColor: "#FFFFFF",
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    padding: 20,
    paddingBottom: Platform.OS === "android" ? 24 : 36,
  },
  modalHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 16,
  },
  modalTitle: {
    fontSize: 18,
    fontWeight: "800",
    color: "#0F172A",
  },
  modalSub: {
    fontSize: 12,
    color: "#64748B",
    marginTop: 2,
  },
  modalCloseBtn: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: "#F1F5F9",
    alignItems: "center",
    justifyContent: "center",
  },
  modalCloseText: {
    fontSize: 14,
    fontWeight: "700",
    color: "#64748B",
  },
  modalAmountBanner: {
    backgroundColor: "#F8FAFC",
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: "center",
    marginBottom: 16,
    borderWidth: 1,
    borderColor: "#E2E8F0",
  },
  modalAmountText: {
    fontSize: 32,
    fontWeight: "900",
    color: "#0F172A",
  },
  modalCurrencyText: {
    fontSize: 12,
    fontWeight: "700",
    color: "#64748B",
    marginTop: 2,
  },
  detailTable: {
    borderTopWidth: 1,
    borderTopColor: "#F1F5F9",
  },
  detailRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: "#F1F5F9",
  },
  detailLabel: {
    fontSize: 13,
    color: "#64748B",
  },
  detailValue: {
    fontSize: 13,
    fontWeight: "600",
    color: "#0F172A",
    maxWidth: "60%",
    textAlign: "right",
  },
  modalActionGroup: {
    flexDirection: "row",
    gap: 12,
    marginTop: 18,
  },
  modalBtn: {
    flex: 1,
    paddingVertical: 14,
    borderRadius: 12,
    alignItems: "center",
    justifyContent: "center",
  },
  modalBtnText: {
    fontSize: 14,
    fontWeight: "800",
    color: "#FFFFFF",
  },
  modalDismissBtn: {
    backgroundColor: "#F1F5F9",
    borderRadius: 12,
    paddingVertical: 12,
    alignItems: "center",
    marginTop: 16,
  },
  modalDismissText: {
    fontSize: 14,
    fontWeight: "700",
    color: "#475569",
  },

  // Discovered Account Cards
  discoveredAccCard: {
    backgroundColor: "#F8FAFC",
    borderRadius: 14,
    padding: 14,
    marginBottom: 10,
    borderWidth: 1,
    borderColor: "#E2E8F0",
  },
  linkedBadge: {
    backgroundColor: "#DCFCE7",
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 6,
  },
  linkedBadgeText: {
    fontSize: 10,
    fontWeight: "800",
    color: "#16A34A",
  },
  linkActionBtn: {
    backgroundColor: "#2563EB",
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 8,
  },
  linkActionBtnText: {
    fontSize: 12,
    fontWeight: "800",
    color: "#FFFFFF",
  },

  // Feed Tab Switcher
  tabContainer: {
    flexDirection: "row",
    backgroundColor: "#F1F5F9",
    borderRadius: 12,
    padding: 4,
    marginBottom: 16,
    gap: 6,
  },
  tabButton: {
    flex: 1,
    paddingVertical: 10,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 8,
  },
  tabButtonActive: {
    backgroundColor: "#2563EB",
    shadowColor: "#2563EB",
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.15,
    shadowRadius: 4,
    elevation: 2,
  },
  tabButtonText: {
    fontSize: 13,
    fontWeight: "700",
    color: "#64748B",
  },
  tabButtonTextActive: {
    color: "#FFFFFF",
  },

  // History Cards
  historyCard: {
    backgroundColor: "#FFFFFF",
    borderRadius: 16,
    padding: 16,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: "#E2E8F0",
  },
  historyDateText: {
    fontSize: 11,
    color: "#94A3B8",
    marginTop: 4,
  },
  reportedBadgeRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    backgroundColor: "#FEF2F2",
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 8,
    marginTop: 10,
    borderWidth: 1,
    borderColor: "#FECACA",
  },
  reportedBadgeText: {
    fontSize: 11,
    fontWeight: "800",
    color: "#DC2626",
    flex: 1,
  },
  viewComplaintBtn: {
    backgroundColor: "#DC2626",
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 6,
    marginLeft: 6,
  },
  viewComplaintBtnText: {
    fontSize: 11,
    fontWeight: "800",
    color: "#FFFFFF",
  },
  reportScamCardBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#FFF1F2",
    borderRadius: 10,
    paddingVertical: 8,
    marginTop: 10,
    borderWidth: 1,
    borderColor: "#FECDD3",
  },
  reportScamCardBtnText: {
    fontSize: 12,
    fontWeight: "800",
    color: "#E11D48",
  },

  // Cyber Crime Report Modal Styles
  reportSummaryBox: {
    backgroundColor: "#F8FAFC",
    borderRadius: 12,
    padding: 12,
    marginBottom: 14,
    borderWidth: 1,
    borderColor: "#E2E8F0",
  },
  reportSummaryTitle: {
    fontSize: 12,
    fontWeight: "800",
    color: "#475569",
    marginBottom: 8,
    textTransform: "uppercase",
  },
  fieldSectionLabel: {
    fontSize: 13,
    fontWeight: "800",
    color: "#0F172A",
    marginBottom: 8,
    marginTop: 6,
  },
  categoryContainer: {
    gap: 8,
    marginBottom: 14,
  },
  categoryChip: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: "#F8FAFC",
    borderRadius: 10,
    paddingVertical: 10,
    paddingHorizontal: 12,
    borderWidth: 1,
    borderColor: "#E2E8F0",
  },
  categoryChipSelected: {
    backgroundColor: "#EFF6FF",
    borderColor: "#3B82F6",
  },
  categoryIcon: {
    fontSize: 16,
    marginRight: 10,
  },
  categoryText: {
    fontSize: 13,
    fontWeight: "600",
    color: "#334155",
    flex: 1,
  },
  categoryTextSelected: {
    color: "#1D4ED8",
    fontWeight: "700",
  },
  notesInput: {
    backgroundColor: "#F8FAFC",
    borderRadius: 10,
    borderWidth: 1,
    borderColor: "#CBD5E1",
    padding: 12,
    fontSize: 13,
    color: "#0F172A",
    textAlignVertical: "top",
    minHeight: 70,
    marginBottom: 12,
  },
  cyberHelplineBanner: {
    flexDirection: "row",
    backgroundColor: "#FEF2F2",
    borderRadius: 10,
    padding: 10,
    borderWidth: 1,
    borderColor: "#FECACA",
    alignItems: "center",
  },
  cyberHelplineTitle: {
    fontSize: 12,
    fontWeight: "800",
    color: "#991B1B",
  },
  cyberHelplineText: {
    fontSize: 11,
    color: "#B91C1C",
    marginTop: 2,
    lineHeight: 15,
  },

  // Ticket Receipt Card Styles
  ticketCard: {
    backgroundColor: "#0F172A",
    borderRadius: 16,
    padding: 20,
    alignItems: "center",
    marginVertical: 12,
  },
  ticketLabel: {
    fontSize: 11,
    fontWeight: "800",
    color: "#94A3B8",
    letterSpacing: 1.5,
  },
  ticketNumber: {
    fontSize: 26,
    fontWeight: "900",
    color: "#38BDF8",
    marginVertical: 8,
    letterSpacing: 2,
  },
  ticketSub: {
    fontSize: 11,
    color: "#94A3B8",
    textAlign: "center",
  },
  receiptHelpBox: {
    backgroundColor: "#EFF6FF",
    borderRadius: 10,
    padding: 12,
    borderWidth: 1,
    borderColor: "#BFDBFE",
  },
  receiptHelpText: {
    fontSize: 12,
    color: "#1E40AF",
    lineHeight: 18,
    fontWeight: "600",
  },
});
