# -*- coding: utf-8 -*-
# Generated by Django 1.11.29 on 2021-01-12 17:41
from __future__ import unicode_literals

import django.contrib.postgres.fields.jsonb
from django.db import migrations
from django.db import models


class Migration(migrations.Migration):

    dependencies = [
        ("contentcuration", "0127_auto_20210107_1821"),
    ]

    operations = [
        migrations.AddField(
            model_name="contentmetadata",
            name="node_ids",
            field=django.contrib.postgres.fields.jsonb.JSONField(default=[]),
        ),
        migrations.RemoveField(
            model_name="contentnode",
            name="metadata",
        ),
        migrations.AddField(
            model_name="contentnode",
            name="metadata",
            field=django.contrib.postgres.fields.jsonb.JSONField(default=[]),
        ),
        migrations.RunSQL(
            """
            CREATE OR REPLACE FUNCTION update_node_after_metadata_deletion() RETURNS trigger AS $update_node_after_metadata_deletion$
                BEGIN
                    update contentcuration_contentnode set metadata=metadata  - OLD.id where metadata @> ('["' || OLD.id || '"]')::jsonb;
                    RETURN OLD;
                END;
            $update_node_after_metadata_deletion$ LANGUAGE plpgsql;

            DROP TRIGGER IF EXISTS update_node_after_metadata_deletion on contentcuration_contentmetadata;
            CREATE TRIGGER update_node_after_metadata_deletion AFTER DELETE ON contentcuration_contentmetadata
                FOR EACH ROW EXECUTE PROCEDURE update_node_after_metadata_deletion();


            CREATE OR REPLACE FUNCTION update_metadata_after_node_deletion() RETURNS trigger AS $update_metadata_after_node_deletion$
                BEGIN
                    update contentcuration_contentmetadata set node_ids=node_ids - OLD.id where node_ids @> ('["' || OLD.id || '"]')::jsonb;
                    RETURN OLD;
                END;
            $update_metadata_after_node_deletion$ LANGUAGE plpgsql;

            DROP TRIGGER IF EXISTS update_metadata_after_node_deletion on contentcuration_contentnode;
            CREATE TRIGGER update_metadata_after_node_deletion AFTER DELETE ON contentcuration_contentnode
                FOR EACH ROW EXECUTE PROCEDURE update_metadata_after_node_deletion();

        """
        ),
    ]
