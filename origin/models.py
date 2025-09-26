from django.contrib.auth.models import User
from django.db import models


class UserProfile(models.Model):
    tg_id = models.CharField(max_length=50, blank=False, null=False)
    token = models.CharField(max_length=50, blank=False, null=False)
    leverage = models.IntegerField(blank=False, null=False)

    def __str__(self):
        return self.tg_id


class Wallet(models.Model):
    wallet = models.CharField(max_length=255, blank=False, null=False)
    balance = models.IntegerField(blank=False, null=False)

    def __str__(self):
        return f"{self.wallet} - {self.balance}"


class Api_Keys(models.Model):
    key = models.CharField(max_length=120)
    sec_key = models.CharField(max_length=120)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='api_keys')
    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name='api_keys')

    def __str__(self):
        return f"{self.key} - {self.user}"
