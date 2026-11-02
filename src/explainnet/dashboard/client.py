"""Local API transport with bounded reads, validation, and no mutation retries."""
import base64
import hashlib
import json
import os
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class ClientSettings(BaseModel):
    model_config = ConfigDict(frozen=True)
    api_url: str = 'http://127.0.0.1:8765'
    timeout_s: float = Field(default=12, ge=1, le=30)

    @field_validator('api_url')
    @classmethod
    def local_api(cls, value):
        u = urlsplit(value)
        if u.scheme != 'http' or u.hostname not in {'127.0.0.1', 'localhost', '::1'} or u.username or u.password or u.query or u.fragment or u.path not in {'', '/'}:
            raise ValueError('Use a loopback HTTP API URL, for example http://127.0.0.1:8765')
        _ = u.port
        return value.rstrip('/')

    @classmethod
    def environment(cls):
        return cls(api_url=os.environ.get('EXPLAINNET_API_URL', 'http://127.0.0.1:8765'))


class ApiError(RuntimeError):
    def __init__(self, message, kind='rejected', request_id=None):
        super().__init__(message)
        self.kind, self.request_id = kind, request_id


class JobAccepted(BaseModel):
    job_id: str
    state: str


class ApiClient:
    def __init__(self, settings=None, transport=None):
        self.settings = settings or ClientSettings.environment()
        self.transport = transport

    def request(self, path, method='GET', body=None, key=None, model=None):
        if not path.startswith('/v1/') or '..' in path or '://' in path:
            raise ValueError('invalid API resource')
        try:
            with httpx.Client(base_url=self.settings.api_url, timeout=httpx.Timeout(self.settings.timeout_s, connect=2),
                    trust_env=False, transport=self.transport, follow_redirects=False) as http, http.stream(method, path, json=body if method != 'GET' else None,
                        headers={'Idempotency-Key': key} if key else {}) as response:
                data = bytearray()
                for block in response.iter_bytes():
                    data.extend(block)
                    if len(data) > 4_000_000:
                        raise ApiError('Response exceeds the dashboard limit. Use a smaller history range.', 'invalid_response')
                try:
                    value = json.loads(data)
                except (ValueError, UnicodeError) as exc:
                    raise ApiError('Backend returned invalid JSON. Check the API URL and backend log.', 'invalid_response') from exc
                if not isinstance(value, dict):
                    raise ApiError('Unexpected backend response shape.', 'invalid_response')
                if response.status_code >= 400:
                    detail = value.get('error') or value.get('detail') or 'Request rejected'
                    if isinstance(detail, dict):
                        detail = detail.get('message', 'Request rejected')
                    if response.status_code == 404 and path.startswith('/v1/dashboard/'):
                        detail = 'Dashboard endpoint unavailable. Restart the updated backend and verify the API URL.'
                    raise ApiError(str(detail), 'unavailable' if response.status_code >= 500 else 'rejected', response.headers.get('x-request-id'))
                if not isinstance(value, dict):
                    raise ApiError('Unexpected backend response shape.', 'invalid_response')
                if method == 'GET' and value.get('response_schema_version') == 2 and value.get('evidence_retrieval'):
                    reference = value['evidence']
                    if not 0 <= reference['bytes'] <= 32 * 1024 * 1024:
                        raise ApiError('Detailed evidence exceeds the bounded retrieval budget. Use the saved native artifact.', 'invalid_response')
                    detailed = bytearray()
                    while len(detailed) < reference['bytes']:
                        page = self.get(value['evidence_retrieval'] + '?offset=' + str(len(detailed)))
                        block = base64.b64decode(page['base64'], validate=True)
                        if (page['sha256'] != reference['sha256'] or page['offset'] != len(detailed)
                                or page['total_bytes'] != reference['bytes'] or not block
                                or len(block) > 49152 or page['next_offset'] != len(detailed) + len(block)):
                            raise ApiError('Detailed evidence identity/offset mismatch. Refresh its source.', 'invalid_response')
                        detailed.extend(block)
                        if len(detailed) > reference['bytes']:
                            raise ApiError('Detailed evidence exceeds its declared size.', 'invalid_response')
                    if hashlib.sha256(detailed).hexdigest() != reference['sha256']:
                        raise ApiError('Detailed evidence integrity mismatch.', 'invalid_response')
                    value = json.loads(detailed)
                    if not isinstance(value, dict):
                        raise ApiError('Unexpected detailed evidence shape.', 'invalid_response')
                return model.model_validate(value).model_dump() if model else value
        except httpx.TimeoutException as exc:
            message = 'Backend timed out. A mutation may have been accepted; check its submission status before doing anything else.' if method != 'GET' else 'Backend timed out. Refresh later or check service health.'
            raise ApiError(message, 'timeout') from exc
        except httpx.RequestError as exc:
            raise ApiError('Backend unavailable. Start the API and verify its configured loopback URL.', 'unavailable') from exc
        except ValidationError as exc:
            raise ApiError('Backend response does not match the expected contract. Check application versions.', 'invalid_response') from exc
        except (ValueError, KeyError, TypeError) as exc:
            raise ApiError('Detailed evidence is malformed or expired. Refresh the source and inspect its retained record.', 'invalid_response') from exc

    def get(self, path, model=None):
        return self.request(path, model=model)

    def submit(self, path, body, key):
        return self.request(path, 'POST', body, key, JobAccepted)
