# -*- coding: utf-8 -*-
# Generated by Django 1.9.13 on 2018-07-12 17:43
from __future__ import unicode_literals

import contentcuration.models
import django.contrib.postgres.fields.jsonb
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('contentcuration', '0088_auto_20180705_2007'),
    ]

    operations = [
        migrations.AddField(
            model_name='contentnode',
            name='changed_staging_fields',
            field=django.contrib.postgres.fields.jsonb.JSONField(null=True),
        ),
    ]
