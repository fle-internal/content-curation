from django.contrib import admin

from contentcuration.models import AssessmentItem
from contentcuration.models import License
from contentcuration.models import User

admin.site.register(AssessmentItem)
admin.site.register(License)


class UserAdmin(admin.ModelAdmin):
    list_display = ('first_name', 'last_name', 'email', 'date_joined',)
    date_hierarchy = 'date_joined'


admin.site.register(User, UserAdmin)
