from django.contrib.auth.models import User
from django.db import models


class UserProfile(models.Model):
    tg_id = models.CharField(max_length=50)

    def __str__(self):
        return self.tg_id


class Token(models.Model):
    symbol = models.CharField(max_length=50)
    leverage = models.IntegerField(default=1)
    price = models.FloatField(blank=False, null=False)

    def __str__(self):
        return f"{self.symbol} - {self.price} - {self.leverage}x"


class Wallet(models.Model):
    wallet = models.CharField(max_length=255)
    balance = models.IntegerField(blank=False, null=False)

    def __str__(self):
        return f"{self.wallet} - {self.balance}"


class ApiKeys(models.Model):
    key = models.CharField(max_length=120)
    sec_key = models.CharField(max_length=120)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='api_keys')
    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name='api_keys')

    def __str__(self):
        return f"{self.key} - {self.user}"


class ProfilesModel(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='profiles')
    wallet_1 = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name='profiles')
    wallet_2 = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name='profiles')
    wallet_3 = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name='profiles')
    api_key_1 = models.ForeignKey(ApiKeys, on_delete=models.CASCADE, related_name='profiles')
    api_key_2 = models.ForeignKey(ApiKeys, on_delete=models.CASCADE, related_name='profiles')
    api_key_3 = models.ForeignKey(ApiKeys, on_delete=models.CASCADE, related_name='profiles')
    token = models.ForeignKey(Token, on_delete=models.CASCADE, related_name='profiles')
    volume = models.IntegerField()

class Proxies(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='proxies')
    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name='proxies')
    adress = models.CharField(max_length=120)
    port = models.IntegerField()
    login = models.CharField(max_length=120)
    password = models.CharField(max_length=120)