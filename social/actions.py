from social.p3 import quote
from social.utils import sanitize_redirect, user_is_authenticated, \
                         user_is_active, partial_pipeline_data, setting_url
from social.apps.django_app.default.models import ObjectTokenSocialAuth
from django.contrib.contenttypes.models import ContentType, ContentTypeManager
from django.core.exceptions import DoesNotExist
from django.conf import settings

def do_auth(backend, redirect_name='next'):
    # Save any defined next value into session
    data = backend.strategy.request_data(merge=False)

    # Save extra data into session.
    for field_name in backend.setting('FIELDS_STORED_IN_SESSION', []):
        if field_name in data:
            backend.strategy.session_set(field_name, data[field_name])

    if redirect_name in data:
        # Check and sanitize a user-defined GET/POST next field value
        redirect_uri = data[redirect_name]
        if backend.setting('SANITIZE_REDIRECTS', True):
            redirect_uri = sanitize_redirect(backend.strategy.request_host(),
                                             redirect_uri)
        backend.strategy.session_set(
            redirect_name,
            redirect_uri or backend.setting('LOGIN_REDIRECT_URL')
        )
    return backend.start()


def do_complete(backend, login, user=None, redirect_name='next',
                *args, **kwargs):
    data = backend.strategy.request_data()
    is_authenticated = user_is_authenticated(user)
    user = is_authenticated and user or None

    if user and backend.strategy.session_get('token'):
        try:
            mapper = ObjectTokenSocialAuth.objects.get(token=backend.strategy.session_get('token'))
            user_type = ContentType.objects.get(pk=mapper.content_type_id)
            user = user_type.get_object_for_this_type(pk=mapper.object_id)
            mapper.delete()
        except DoesNotExist:
            if settings.DEBUG:
                print("Object Token Social Auth not found")

    partial = partial_pipeline_data(backend, user, *args, **kwargs)
    if partial:
        xargs, xkwargs = partial
        user = backend.continue_pipeline(*xargs, **xkwargs)
    else:
        user = backend.complete(user=user, *args, **kwargs)

    # pop redirect value before the session is trashed on login(), but after
    # the pipeline so that the pipeline can change the redirect if needed
    redirect_value = backend.strategy.session_get(redirect_name, '') or \
                     data.get(redirect_name, '')

    user_model = user_type.model_class()
    if user and not isinstance(user, user_model):
        return user

    if is_authenticated:
        if not user:
            url = setting_url(backend, redirect_value, 'LOGIN_REDIRECT_URL')
        else:
            url = setting_url(backend, redirect_value,
                              'NEW_ASSOCIATION_REDIRECT_URL',
                              'LOGIN_REDIRECT_URL')
    elif user:
        if user_is_active(user):
            # catch is_new/social_user in case login() resets the instance
            is_new = getattr(user, 'is_new', False)
            social_user = user.social_user
            login(backend, user, social_user)
            # store last login backend name in session
            backend.strategy.session_set('social_auth_last_login_backend',
                                         social_user.provider)

            if is_new:
                url = setting_url(backend,
                                  'NEW_USER_REDIRECT_URL',
                                  redirect_value,
                                  'LOGIN_REDIRECT_URL')
            else:
                url = setting_url(backend, redirect_value,
                                  'LOGIN_REDIRECT_URL')
        else:
            url = setting_url(backend, 'INACTIVE_USER_URL', 'LOGIN_ERROR_URL',
                              'LOGIN_URL')
    else:
        url = setting_url(backend, 'LOGIN_ERROR_URL', 'LOGIN_URL')

    if redirect_value and redirect_value != url:
        redirect_value = quote(redirect_value)
        url += ('?' in url and '&' or '?') + \
               '{0}={1}'.format(redirect_name, redirect_value)

    if backend.setting('SANITIZE_REDIRECTS', True):
        url = sanitize_redirect(backend.strategy.request_host(), url) or \
              backend.setting('LOGIN_REDIRECT_URL')
    return backend.strategy.redirect(url)


def do_disconnect(backend, user, association_id=None, redirect_name='next',
                  *args, **kwargs):
    partial = partial_pipeline_data(backend, user, *args, **kwargs)
    if partial:
        xargs, xkwargs = partial
        if association_id and not xkwargs.get('association_id'):
            xkwargs['association_id'] = association_id
        response = backend.disconnect(*xargs, **xkwargs)
    else:
        response = backend.disconnect(user=user, association_id=association_id,
                                      *args, **kwargs)

    if isinstance(response, dict):
        response = backend.strategy.redirect(
            backend.strategy.request_data().get(redirect_name, '') or
            backend.setting('DISCONNECT_REDIRECT_URL') or
            backend.setting('LOGIN_REDIRECT_URL')
        )
    return response
