import sys
import json
import time
import unittest
from threading import Thread

from http.server import SimpleHTTPRequestHandler, HTTPServer

import bugsnag


try:
    import exceptiongroup # noqa
    is_exception_group_supported = True
except ImportError:
    is_exception_group_supported = sys.version_info >= (3, 11)


class MissingRequestError(Exception):
    pass


class IntegrationTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.server = FakeBugsnagServer(wait_for_duplicate_requests=False)

    def setUp(self):
        self.server.received = []

    def tearDown(self):
        bugsnag.legacy.default_client.uninstall_sys_hook()
        client = bugsnag.Client()
        client.configuration.api_key = 'some key'
        bugsnag.legacy.default_client = client
        bugsnag.legacy.configuration = client.configuration

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def assertSentReportCount(self, count):
        self.assertEqual(len(self.server.received), count)

    def assertExceptionName(self, received_index, event_index, name):
        json_body = self.server.received[received_index]['json_body']
        event = json_body['events'][event_index]
        exception = event['exceptions'][0]
        self.assertEqual(exception['errorClass'], name)

    @property
    def sent_report_count(self) -> int:
        return self.server.sent_report_count


class FakeBugsnagServer(object):
    """
    A server which accepts a single request, recording the JSON payload and
    other request information
    """

    def __init__(self, wait_for_duplicate_requests: bool):
        self.received = []
        self.paused = False
        self.wait_for_duplicate_requests = wait_for_duplicate_requests

        class Handler(SimpleHTTPRequestHandler):

            def do_POST(handler):
                start = time.time()

                while self.paused:
                    if time.time() > (start + 0.5):
                        raise Exception('Paused HTTP server timeout')

                    time.sleep(0.001)

                length = int(handler.headers['Content-Length'])
                raw_body = handler.rfile.read(length).decode('utf-8')
                if handler.path != '/ignore':
                    self.received.append({'headers': handler.headers,
                                          'json_body': json.loads(raw_body),
                                          'path': handler.path,
                                          'method': handler.command})
                handler.send_response(200)
                handler.end_headers()
                return ()

            def log_request(self, *args):
                pass

        self.server = HTTPServer(('localhost', 0), Handler)
        self.server.timeout = 0.5
        self.thread = Thread(target=self.server.serve_forever, args=(0.1,))
        self.thread.daemon = True
        self.thread.start()

    @property
    def address(self):
        return '{0}:{1}'.format(*self.server.server_address)

    @property
    def url(self):
        return 'http://%s' % self.address

    def shutdown(self):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()
        self.received = []

    def wait_for_request(self, timeout=2):
        start = time.time()

        while len(self.received) == 0:
            if time.time() - start > timeout:
                raise MissingRequestError("No request received before timeout")

            time.sleep(0.01)

        # sleep for the time remaining until 'timeout' to allow more requests
        # to arrive
        if self.wait_for_duplicate_requests:
            time.sleep(timeout - (time.time() - start))

    @property
    def sent_report_count(self) -> int:
        return len(self.received)


class ScaryException(Exception):
    class NestedScaryException(Exception):
        pass
