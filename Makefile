prodserver: migrate collectstatic ensurecrowdinclient downloadmessages compilemessages
	cd contentcuration/ && gunicorn contentcuration.wsgi:application --timeout=500 --error-logfile=/var/log/gunicorn-error.log --workers=3 --bind=0.0.0.0:8000 --pid=/tmp/contentcuration.pid --log-level=debug || sleep infinity

# temporary copy of prodserver to match our config in nanobox, until we move out of our v1 deployscripts
altprodserver: migrate collectstatic ensurecrowdinclient downloadmessages compilemessages
	cd contentcuration/ && gunicorn contentcuration.wsgi:application --timeout=500 --error-logfile=/var/log/gunicorn-error.log --workers=3 --bind=0.0.0.0:8081 --pid=/tmp/contentcuration.pid --log-level=debug || sleep infinity

dummyusers:
	cd contentcuration/ && python manage.py loaddata contentcuration/fixtures/admin_user.json
	cd contentcuration/ && python manage.py loaddata contentcuration/fixtures/admin_user_token.json

prodceleryworkers:
	cd contentcuration/ && celery -A contentcuration worker -l info

setupnanobox:
	nanobox evar add dry-run DJANGO_SETTINGS_MODULE=contentcuration.dry_run_settings
	nanobox evar add dry-run DJANGO_SETTINGS_MODULE=contentcuration.dev_settings
	nanobox evar add local MINIO_ACCESS_KEY=development
	nanobox evar add local MINIO_SECRET_KEY=development
	nanobox evar add dry-run MINIO_ACCESS_KEY=development
	nanobox evar add dry-run MINIO_SECRET_KEY=development
	nanobox evar add local MINIO_RUN_TYPE=LOCAL
	nanobox evar add dry-run MINIO_RUN_TYPE=LOCAL


devserver:
	cd contentcuration; python manage.py runserver --settings=contentcuration.dev_settings 0.0.0.0:8080

collectstatic: migrate
	python contentcuration/manage.py collectstatic --noinput
	python contentcuration/manage.py collectstatic_js_reverse
	python contentcuration/manage.py loadconstants

migrate:
	python contentcuration/manage.py migrate || true

ensurecrowdinclient:
  ls -l crowdin-cli.jar || curl -L https://storage.googleapis.com/le-downloads/crowdin-cli/crowdin-cli.jar -o crowdin-cli.jar

makemessages:
	# generate frontend messages
	npm run makemessages
	# generate backend messages
	python contentcuration/manage.py makemessages

uploadmessages: ensurecrowdinclient
	java -jar /contentcuration/crowdin-cli.jar upload sources

# we need to depend on makemessages, since CrowdIn requires the en folder to be populated
# in order for it to properly extract strings
downloadmessages: ensurecrowdinclient makemessages
	java -jar crowdin-cli.jar download || true

compilemessages:
	python contentcuration/manage.py compilemessages

# When using apidocs, this should clean out all modules
clean-docs:
	$(MAKE) -C docs clean

docs: clean-docs
	# Adapt to apidocs
	# sphinx-apidoc -d 10 -H "Python Reference" -o docs/py_modules/ kolibri kolibri/test kolibri/deployment/ kolibri/dist/
	$(MAKE) -C docs html
