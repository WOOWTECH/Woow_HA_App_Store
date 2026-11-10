import hashlib
from pathlib import Path
import shlex
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ssh_transport import ssh_run, TransportError, connect


class Channel:
    """A channel with an empty window after early exit-status, before final EOF.

    Its stdout window is blocked until stderr is drained. Stdin accepts partial
    writes only while output is being consumed. This catches sequential readers.
    """
    def __init__(self, size, exit_code=0):
        self.expected_out = bytes(range(256))*(size//256)
        self.expected_err = bytes(reversed(range(256)))*257
        self.out = bytearray(self.expected_out)
        self.err = bytearray(self.expected_err)
        self.eof_received = False
        self.closed = False
        self.input = bytearray()
        self.ended = False
        self.polls = 0
        self.exit_code = exit_code
        self.command = None
        self.timeout = None

    def settimeout(self, value): self.timeout = value
    def exec_command(self, command): self.command = command
    def exit_status_ready(self): return True  # status delivered before any bytes
    def recv_exit_status(self):
        assert self.eof_received and not self.out and not self.err
        return self.exit_code
    def recv_ready(self):
        self.polls += 1
        if self.polls < 5: return False  # empty buffers do not imply EOF
        if not self.out and not self.err and self.ended: self.eof_received = True
        return bool(self.out) and len(self.err) < len(self.expected_err)
    def recv_stderr_ready(self): return self.polls >= 5 and bool(self.err)
    def recv(self, count):
        value = bytes(self.out[:min(count,8191)])
        del self.out[:len(value)]
        return value
    def recv_stderr(self, count):
        value = bytes(self.err[:min(count,4093)])
        del self.err[:len(value)]
        return value
    def send_ready(self): return self.polls >= 5
    def send(self, data):
        size = min(len(data),4091)
        self.input.extend(data[:size])
        return size
    def shutdown_write(self): self.ended = True
    def close(self): self.closed = True


class Client:
    def __init__(self, channel): self.channel = channel
    def get_transport(self): return self
    def open_session(self, timeout): return self.channel


class TransportTests(unittest.TestCase):
    def test_binary_sizes_late_eof_and_full_duplex(self):
        for size in (2*1024*1024,4*1024*1024):
            with self.subTest(size=size):
                channel = Channel(size,exit_code=7)
                data = bytes(range(256))*8192
                argv = ['printf','a b',"quote'and\"",'$(not-executed)',';']
                result = ssh_run(Client(channel),argv,data,timeout=5)
                self.assertEqual(result.returncode,7)
                for actual,expected in [(result.stdout,channel.expected_out),(result.stderr,channel.expected_err)]:
                    self.assertEqual(len(actual),len(expected))
                    self.assertEqual(hashlib.sha256(actual).digest(),hashlib.sha256(expected).digest())
                self.assertEqual(bytes(channel.input),data)
                self.assertEqual(shlex.split(channel.command),argv)
                self.assertTrue(channel.ended and channel.closed)

    def test_output_bound_closes_channel(self):
        for stream in ('stdout','stderr'):
            with self.subTest(stream=stream):
                channel=Channel(2*1024*1024)
                if stream=='stdout': channel.err.clear()
                with self.assertRaisesRegex(TransportError,'output limit'):
                    ssh_run(Client(channel),['read'],max_output=100)
                self.assertTrue(channel.closed)

    def test_deadline_closes_channel(self):
        channel=Channel(0)
        with patch('ssh_transport.time.monotonic',side_effect=[0,10]):
            with self.assertRaisesRegex(TransportError,'deadline'):
                ssh_run(Client(channel),['read'],timeout=1)
        self.assertTrue(channel.closed)

    def test_premature_input_close(self):
        channel=Channel(0)
        channel.send=lambda data:0
        with self.assertRaisesRegex(TransportError,'stdin closed'):
            ssh_run(Client(channel),['read'],stdin=b'data')
        self.assertTrue(channel.closed)

    def test_no_default_credentials(self):
        for kwargs in ({},{'identity':'explicit','agent':True}):
            with self.assertRaises(TransportError): connect('example.invalid','tester','known_hosts',**kwargs)

    def test_bad_arguments_fail_before_connection(self):
        for argv,timeout,limit in [([],5,1),(['a\0b'],5,1),(['a'],float('nan'),1),(['a'],5,0)]:
            with self.assertRaises(TransportError): ssh_run(None,argv,timeout=timeout,max_output=limit)


if __name__ == '__main__': unittest.main()
