# -*- coding: utf-8 -*-
# Generated by Django 1.9.13 on 2018-07-31 17:30
from __future__ import unicode_literals

import contentcuration.models
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('contentcuration', '0091_auto_20180724_2243'),
    ]

    operations = [
        migrations.AlterField(
            model_name='contentnode',
            name='changed',
            field=models.BooleanField(default=True),
        ),
    ]
