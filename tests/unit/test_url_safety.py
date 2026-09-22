import httpx
import pytest

from careerviet.ingestion.http_client import SafeHttpClient, UnsafeUrlError


@pytest.mark.parametrize('address', ['127.0.0.1', '10.0.0.1', '169.254.169.254', '::1',
                                     '100.64.0.1', '0.0.0.0', 'fe80::1', '224.0.0.1'])
def test_nonpublic_dns_never_reaches_transport(tmp_path, address):
    seen = []
    with SafeHttpClient(tmp_path, {'example.org'}, dns_resolver=lambda _: [address],
                        transport=httpx.MockTransport(lambda req: seen.append(req) or httpx.Response(200))) as client, pytest.raises(UnsafeUrlError):
        client.fetch('GET', 'https://example.org/job')
    assert not seen


def test_redirect_revalidates_private_destination(tmp_path):
    seen = []
    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(302, headers={'Location': 'https://internal.example/job'})
    with SafeHttpClient(tmp_path, {'example.org', 'internal.example'},
                        dns_resolver=lambda host: ['8.8.8.8'] if host == 'example.org' else ['127.0.0.1'],
                        transport=httpx.MockTransport(handler)) as client, pytest.raises(UnsafeUrlError):
        client.fetch('GET', 'https://example.org/job')
    assert seen == ['https://example.org/job']
