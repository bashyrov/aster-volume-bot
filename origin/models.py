from django.contrib.auth.models import User
from django.db import models


class UserProfile(models.Model):
    tg_id = models.CharField(max_length=50)

    def __str__(self):
        return self.tg_id


class Token(models.Model):
    name = models.CharField(max_length=50)
    symbol = models.CharField(max_length=50)
    leverage = models.IntegerField(default=1)
    price = models.FloatField(blank=False, null=False)

    def __str__(self):
        return f"{self.symbol} - {self.price} - {self.leverage}x"

#1
class ApiKeys(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='api_keys')
    key = models.CharField(max_length=120)
    sec_key = models.CharField(max_length=120)

    def __str__(self):
        return f"{self.key} - {self.user}"


class Proxies(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='proxies')
    address = models.CharField(max_length=120)

    def __str__(self):
        return self.address


class Wallet(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='wallets')  # изменил здесь
    wallet = models.CharField(max_length=255)
    balance = models.IntegerField(blank=False, null=False)
    apikey = models.OneToOneField(ApiKeys, on_delete=models.CASCADE, related_name='wallet')
    is_used = models.BooleanField(default=False)
    proxy = models.OneToOneField(Proxies, on_delete=models.CASCADE, related_name='wallet')

    def __str__(self):
        return f"{self.wallet} - {self.balance}$"


class ProfilesModel(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='profiles')
    wallet_1 = models.OneToOneField(Wallet, on_delete=models.CASCADE, related_name='profile_wallet1')
    wallet_2 = models.OneToOneField(Wallet, on_delete=models.CASCADE, related_name='profile_wallet2')
    wallet_3 = models.OneToOneField(Wallet, on_delete=models.CASCADE, related_name='profile_wallet3')
    token = models.ForeignKey(Token, on_delete=models.CASCADE, related_name='profiles')
    volume = models.IntegerField()

