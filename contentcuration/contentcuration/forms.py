from contentcuration.models import User
from django import forms
from django.utils.translation import ugettext as _
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm, UserChangeForm, PasswordChangeForm

class RegistrationForm(UserCreationForm):
    password1 = forms.CharField(widget=forms.PasswordInput, label='Password', required=True)
    password2 = forms.CharField(widget=forms.PasswordInput, label='Password (again)', required=True)

    class Meta:
        model = User
        fields = ('first_name', 'last_name', 'email', 'password1', 'password2')

    def clean_email(self):
        email = self.cleaned_data['email'].strip()
        if User.objects.filter(email__iexact=email, is_active=True).exists():
            self.add_error('email', 'Email already exists.')
        else:
            return email

    def clean(self):
        cleaned_data = super(RegistrationForm, self).clean()

        self.check_field('email', 'Email is required.')
        self.check_field('first_name', 'First name is required.')
        self.check_field('last_name', 'Last name is required.')

        if self.check_field('password1', 'Password is required.'):
            if 'password2' not in self.cleaned_data or self.cleaned_data['password1'] != self.cleaned_data['password2']:
                self.errors['password2'] = self.error_class()
                self.add_error('password2', 'Passwords don\'t match.')
        else:
            self.errors['password2'] = self.error_class()

        return self.cleaned_data

    def check_field(self, field, error):
        if field not in self.cleaned_data:
            self.errors[field] = self.error_class()
            self.add_error(field, error)
            return False
        return True


class InvitationForm(UserCreationForm):
    password1 = forms.CharField(widget=forms.PasswordInput, label='Password', required=True)
    password2 = forms.CharField(widget=forms.PasswordInput, label='Password (again)', required=True)

    class Meta:
        model = User
        fields = ('first_name', 'last_name', 'password1', 'password2')

    def clean_email(self):
        email = self.cleaned_data['email'].strip()
        return email

    def clean(self):
        cleaned_data = super(InvitationForm, self).clean()

        self.check_field('first_name', 'First name is required.')
        self.check_field('last_name', 'Last name is required.')

        if self.check_field('password1', 'Password is required.'):
            if 'password2' not in self.cleaned_data or self.cleaned_data['password1'] != self.cleaned_data['password2']:
                self.errors['password2'] = self.error_class()
                self.add_error('password2', 'Passwords don\'t match.')
        else:
            self.errors['password2'] = self.error_class()

        return self.cleaned_data

    def check_field(self, field, error):
        if field not in self.cleaned_data:
            self.errors[field] = self.error_class()
            self.add_error(field, error)
            return False
        return True

    def save(self, user):
        user.set_password(self.cleaned_data["password1"])
        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]
        user.is_active=True
        user.save()
        return user


class InvitationAcceptForm(AuthenticationForm):
    user=None
    password = forms.CharField(widget=forms.PasswordInput, label='Password', required=True)

    class Meta:
        model = User
        fields = ('password',)

    def __init__(self, *args, **kwargs):
        self.user =kwargs.pop('user')
        super(InvitationAcceptForm, self).__init__(*args, **kwargs)

    def clean(self):
        if 'password' not in self.cleaned_data:
            self.errors['password'] = self.error_class()
            self.add_error('password', 'Password is required.')
        elif not self.user.check_password(self.cleaned_data["password"]):
            self.errors['password'] = self.error_class()
            self.add_error('password', 'Password is incorrect.')
        else:
            self.confirm_login_allowed(self.user)
        return self.cleaned_data

class ProfileSettingsForm(UserChangeForm):
    first_name = forms.CharField(widget=forms.TextInput(attrs={'class': 'form-control setting_input'}))
    last_name = forms.CharField(widget=forms.TextInput(attrs={'class': 'form-control setting_input'}))

    class Meta:
        model = User
        fields = ('first_name', 'last_name')
        exclude =  ('password', 'email')

    def clean_password(self):
        pass

    def clean(self):
        cleaned_data = super(ProfileSettingsForm, self).clean()

        if 'first_name' not in self.cleaned_data:
            self.errors['first_name'] = self.error_class()
            self.add_error('first_name', 'First name is required.')

        if 'last_name' not in self.cleaned_data:
            self.errors['last_name'] = self.error_class()
            self.add_error('last_name', 'Last name is required.')

        return self.cleaned_data

    def save(self, user):
        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]
        user.save()
        return user

    def __init__(self, *args, **kwargs):
        super(ProfileSettingsForm, self).__init__(*args, **kwargs)


class AccountSettingsForm(PasswordChangeForm):
    old_password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-control setting_input'}))
    new_password1 = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-control setting_input'}))
    new_password2 = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-control setting_input'}))

    class Meta:
        model = User
        fields = ('old_password', 'new_password1', 'new_password2')

    def clean(self):
        cleaned_data = super(AccountSettingsForm, self).clean()

        self.check_field('old_password', 'Current password is incorrect.')

        if self.check_field('new_password1', 'New password is required.'):
            if 'new_password2' not in self.cleaned_data or self.cleaned_data['new_password1'] != self.cleaned_data['new_password2']:
                self.errors['new_password2'] = self.error_class()
                self.add_error('new_password2', 'New passwords don\'t match.')
        else:
            self.errors['new_password2'] = self.error_class()

        return self.cleaned_data

    def check_field(self, field, error):
        if field not in self.cleaned_data:
            self.errors[field] = self.error_class()
            self.add_error(field, error)
            return False
        return True
