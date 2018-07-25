# -*- coding: utf-8 -*-
# Generated by Django 1.9.13 on 2018-06-26 17:55
from __future__ import unicode_literals

import django.contrib.postgres.fields.jsonb
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('contentcuration', '0085_user_policies'),
    ]

    operations = [
        migrations.AlterField(
            model_name='channel',
            name='content_defaults',
            field=django.contrib.postgres.fields.jsonb.JSONField(default={b'author': None, b'auto_derive_audio_thumbnail': True, b'auto_derive_document_thumbnail': True, b'auto_derive_exercise_thumbnail': True, b'auto_derive_html5_thumbnail': True, b'auto_derive_video_thumbnail': True, b'auto_randomize_questions': True, b'copyright_holder': None, b'language': None, b'license': None, b'license_description': None, b'm_value': 5, b'mastery_model': b'num_correct_in_a_row_5', b'n_value': 5}),
        ),
        migrations.AlterField(
            model_name='user',
            name='content_defaults',
            field=django.contrib.postgres.fields.jsonb.JSONField(default={b'author': None, b'auto_derive_audio_thumbnail': True, b'auto_derive_document_thumbnail': True, b'auto_derive_exercise_thumbnail': True, b'auto_derive_html5_thumbnail': True, b'auto_derive_video_thumbnail': True, b'auto_randomize_questions': True, b'copyright_holder': None, b'language': None, b'license': None, b'license_description': None, b'm_value': 5, b'mastery_model': b'num_correct_in_a_row_5', b'n_value': 5}),
        ),
        migrations.AlterField(
            model_name='user',
            name='information',
            field=django.contrib.postgres.fields.jsonb.JSONField(null=True),
        ),
        migrations.AlterField(
            model_name='user',
            name='policies',
            field=django.contrib.postgres.fields.jsonb.JSONField(default=dict),
        ),
    ]
