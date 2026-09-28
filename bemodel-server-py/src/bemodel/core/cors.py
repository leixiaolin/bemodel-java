"""Spring CorsFilter behavior for the original /api/** wildcard configuration."""
from urllib.parse import urlsplit
from starlette.datastructures import Headers, MutableHeaders, URL
from starlette.responses import Response


class CorsMiddleware:
    VARY = ('Origin', 'Access-Control-Request-Method', 'Access-Control-Request-Headers')

    def __init__(self, app):
        self.app = app

    @staticmethod
    def same_origin(origin, request_url):
        def parts(value):
            url = urlsplit(str(value))
            return url.scheme, url.hostname, url.port or (443 if url.scheme == 'https' else 80)
        try:
            return parts(origin) == parts(request_url)
        except ValueError:
            return False

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        headers = Headers(scope=scope)
        origin = headers.get('origin')
        preflight = scope['method'] == 'OPTIONS' and origin is not None and headers.get('access-control-request-method') is not None
        configured = scope['path'] == '/api' or scope['path'].startswith('/api/')
        cross_origin = origin is not None and not self.same_origin(origin, URL(scope=scope))

        async def cors_send(message):
            if message['type'] == 'http.response.start':
                response_headers = MutableHeaders(scope=message)
                vary = [v.strip() for v in response_headers.get('vary', '').split(',') if v.strip()]
                for name in self.VARY:
                    if name.lower() not in {v.lower() for v in vary}:
                        vary.append(name)
                response_headers['vary'] = ', '.join(vary)
                if cross_origin and configured:
                    response_headers['access-control-allow-origin'] = origin
                    if preflight:
                        response_headers['access-control-allow-methods'] = headers['access-control-request-method']
                        requested = headers.get('access-control-request-headers')
                        if requested:
                            response_headers['access-control-allow-headers'] = ', '.join(v.strip() for v in requested.split(',') if v.strip())
            await send(message)

        if preflight:
            response = Response('Invalid CORS request', status_code=403) if cross_origin and not configured else Response(status_code=200)
            return await response(scope, receive, cors_send)
        await self.app(scope, receive, cors_send)
