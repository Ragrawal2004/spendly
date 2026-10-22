import secrets


def csrf_token(client):
    with client.session_transaction() as sess:
        token = sess.get("csrf_token")
        if not token:
            token = secrets.token_urlsafe(32)
            sess["csrf_token"] = token
    return token


def post_form(client, url, data=None, **kwargs):
    data = dict(data or {})
    if "csrf_token" not in data:
        data["csrf_token"] = csrf_token(client)
    return client.post(url, data=data, **kwargs)
