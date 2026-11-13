import random
import uuid
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.db import transaction

from customers.models import BankCustomer
from accounts.models import BankAccount
from payments.models import Beneficiary

FIRST_NAMES = [
    "Aarav", "Aditi", "Advait", "Akash", "Ananya", "Aniket", "Ankita", "Arjun", "Aryan", "Bhavna",
    "Chetan", "Deepak", "Devanshi", "Dhruv", "Divya", "Gaurav", "Gayatri", "Harsh", "Isha", "Ishaan",
    "Jatin", "Kavya", "Kiran", "Kunal", "Lakshmi", "Madhav", "Manish", "Meera", "Mihir", "Neha",
    "Nikhil", "Nisha", "Omkar", "Pooja", "Pranav", "Prateek", "Priyanka", "Radha", "Rajesh", "Rakesh",
    "Rhea", "Rishi", "Rohan", "Rohit", "Roshni", "Sameer", "Sanjay", "Sanya", "Sarthak", "Shreya",
    "Siddharth", "Simran", "Sneha", "Soham", "Sonali", "Sparsh", "Sunil", "Suresh", "Tanvi", "Tarun",
    "Uday", "Utkarsh", "Vaibhav", "Varun", "Vedant", "Vidya", "Vikas", "Vikram", "Vinay", "Vishal",
    "Yash", "Yuvraj", "Aayush", "Abhay", "Abhishek", "Alok", "Amrita", "Anita", "Anmol", "Archana",
    "Ashish", "Avinash", "Barkha", "Bhavesh", "Chirag", "Deepika", "Ekta", "Girish", "Hemant", "Inder",
    "Jaspreet", "Kajal", "Kartik", "Kishore", "Lavanya", "Mayank", "Naveen", "Pallavi", "Pankaj", "Reema"
]

LAST_NAMES = [
    "Sharma", "Patel", "Verma", "Gupta", "Malhotra", "Mehta", "Iyer", "Nair", "Reddy", "Chauhan",
    "Joshi", "Bhatia", "Deshmukh", "Kulkarni", "Chopra", "Singhania", "Bansal", "Agarwal", "Kapoor", "Mishra",
    "Pandey", "Saxena", "Trivedi", "Menon", "Pillai", "Das", "Ghosh", "Mukherjee", "Chatterjee", "Roy",
    "Banerjee", "Bose", "Dutta", "Sengupta", "Yadav", "Choudhary", "Thakur", "Singh", "Kumar", "Prasad",
    "Rao", "Hegde", "Shetty", "Kamath", "Shenoy", "Pai", "Naik", "Mahajan", "Kadam", "Shinde"
]

MERCHANTS = [
    {"name": "Amazon India", "ifsc": "HDFC0000001", "bank": "HDFC Bank", "acc_prefix": "990001"},
    {"name": "Flipkart Payments", "ifsc": "ICIC0000002", "bank": "ICICI Bank", "acc_prefix": "990002"},
    {"name": "Zomato Payments", "ifsc": "SBIN0000003", "bank": "State Bank of India", "acc_prefix": "990003"},
    {"name": "Swiggy Instamart", "ifsc": "UTIB0000004", "bank": "Axis Bank", "acc_prefix": "990004"},
    {"name": "Tata Neu Digital", "ifsc": "PUNB0000005", "bank": "Punjab National Bank", "acc_prefix": "990005"},
    {"name": "MakeMyTrip India", "ifsc": "KKBK0000006", "bank": "Kotak Mahindra Bank", "acc_prefix": "990006"},
]

class Command(BaseCommand):
    help = "Seeds Dummy Bank database with 100 realistic customers and accounts."

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Seeding Dummy Bank with 100 Indian customers and accounts..."))

        # 1. Ensure Demo Accounts for testing are always present
        with transaction.atomic():
            rahul, _ = BankCustomer.objects.get_or_create(
                phone_number="9000000001",
                defaults={
                    "customer_id": uuid.UUID("11111111-1111-1111-1111-111111111101"),
                    "full_name": "Rahul Sharma",
                    "email": "rahul.sharma@payshield.demo",
                    "is_active": True,
                }
            )
            rahul_acc, _ = BankAccount.objects.get_or_create(
                account_number="100000000001",
                defaults={
                    "customer": rahul,
                    "bank_name": "PayShield Demo Bank",
                    "ifsc_code": "PSHD0001001",
                    "account_type": "SAVINGS",
                    "balance": Decimal("50000.00"),
                    "currency": "INR",
                    "status": "ACTIVE",
                }
            )

            priya, _ = BankCustomer.objects.get_or_create(
                phone_number="9000000002",
                defaults={
                    "customer_id": uuid.UUID("22222222-2222-2222-2222-222222222202"),
                    "full_name": "Priya Patil",
                    "email": "priya.patil@payshield.demo",
                    "is_active": True,
                }
            )
            priya_acc, _ = BankAccount.objects.get_or_create(
                account_number="100000000002",
                defaults={
                    "customer": priya,
                    "bank_name": "PayShield Demo Bank",
                    "ifsc_code": "PSHD0001001",
                    "account_type": "SAVINGS",
                    "balance": Decimal("35000.00"),
                    "currency": "INR",
                    "status": "ACTIVE",
                }
            )

            # Ensure default mutual beneficiary
            Beneficiary.objects.get_or_create(
                owner_account=rahul_acc,
                recipient_account_number=priya_acc.account_number,
                defaults={
                    "recipient_name": priya.full_name,
                    "recipient_bank_name": priya_acc.bank_name,
                    "recipient_ifsc": priya_acc.ifsc_code,
                    "is_active": True,
                }
            )

            # 2. Seed 100 accounts (9820000001 to 9820000100)
            created_count = 0
            for i in range(1, 101):
                phone = f"982000{i:04d}"
                first_name = FIRST_NAMES[(i - 1) % len(FIRST_NAMES)]
                last_name = LAST_NAMES[((i - 1) * 3) % len(LAST_NAMES)]
                full_name = f"{first_name} {last_name}"
                email = f"{first_name.lower()}.{last_name.lower()}{i}@example.com"
                acc_num = f"10000000{i:04d}"

                cust, cust_created = BankCustomer.objects.get_or_create(
                    phone_number=phone,
                    defaults={
                        "customer_id": uuid.uuid5(uuid.NAMESPACE_DNS, f"payshield-bank-{phone}"),
                        "full_name": full_name,
                        "email": email,
                        "is_active": True,
                    }
                )

                # Random realistic balance between 8,000 and 2,50,000
                random_balance = Decimal(str(random.randint(80, 2500) * 100))
                acc_type = "CURRENT" if i % 6 == 0 else "SAVINGS"

                acc, acc_created = BankAccount.objects.get_or_create(
                    account_number=acc_num,
                    defaults={
                        "customer": cust,
                        "bank_name": "PayShield Demo Bank",
                        "ifsc_code": "PSHD0001001",
                        "account_type": acc_type,
                        "balance": random_balance,
                        "currency": "INR",
                        "status": "ACTIVE",
                    }
                )

                # Add 2-3 standard merchant beneficiaries for every account
                selected_merchants = random.sample(MERCHANTS, 2)
                for m in selected_merchants:
                    Beneficiary.objects.get_or_create(
                        owner_account=acc,
                        recipient_name=m["name"],
                        defaults={
                            "recipient_bank_name": m["bank"],
                            "recipient_account_number": f"{m['acc_prefix']}{i:04d}",
                            "recipient_ifsc": m["ifsc"],
                            "is_active": True,
                        }
                    )

                if cust_created or acc_created:
                    created_count += 1

        total_customers = BankCustomer.objects.count()
        total_accounts = BankAccount.objects.count()

        self.stdout.write(self.style.SUCCESS(
            f"Successfully seeded database! Total customers: {total_customers}, Total accounts: {total_accounts}."
        ))

