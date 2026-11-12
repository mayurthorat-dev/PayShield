from rest_framework import serializers


class OTPGenerateSerializer(serializers.Serializer):
    transaction_id = serializers.UUIDField()