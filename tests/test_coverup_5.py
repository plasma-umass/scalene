# file scalene/scalene_preload.py:15-55
# lines [15, 16, 17, 18, 19, 25, 26, 27, 28, 31, 32, 34, 36, 37, 39, 40, 42, 43, 44, 46, 48, 49, 51, 53, 55]
# branches ['25->26', '25->36', '26->27', '26->34', '31->32', '31->34', '36->37', '36->51', '37->39', '37->55', '42->43', '42->46', '48->49', '48->55', '51->53', '51->55']

import argparse
import os
import sys
from unittest.mock import patch
import pytest
import scalene.scalene_preload

@pytest.fixture
def args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--allocation_sampling_window', type=int, default=1)
    parser.add_argument('--memory', action='store_true')
    return parser.parse_args([])

@pytest.fixture
def clean_environ():
    original_environ = os.environ.copy()
    yield
    os.environ = original_environ

def test_get_preload_environ_darwin_memory(args, clean_environ):
    args.memory = True
    with patch.object(sys, 'platform', 'darwin'):
        env = scalene.scalene_preload.ScalenePreload.get_preload_environ(args)
        assert 'DYLD_INSERT_LIBRARIES' in env
        assert 'libscalene.dylib' in env['DYLD_INSERT_LIBRARIES']
        assert env['OBJC_DISABLE_INITIALIZE_FORK_SAFETY'] == 'YES'

def test_get_preload_environ_linux_memory(args, clean_environ):
    args.memory = True
    with patch.object(sys, 'platform', 'linux'):
        with patch.dict('os.environ', {'PYTHONMALLOC': 'malloc'}):
            env = scalene.scalene_preload.ScalenePreload.get_preload_environ(args)
            assert 'LD_PRELOAD' in env
            assert 'libscalene.so' in env['LD_PRELOAD']
            assert 'PYTHONMALLOC' not in env

def test_get_preload_environ_linux_no_memory(args, clean_environ):
    args.memory = False
    with patch.object(sys, 'platform', 'linux'):
        env = scalene.scalene_preload.ScalenePreload.get_preload_environ(args)
        assert 'LD_PRELOAD' not in env

def test_get_preload_environ_win32(args, clean_environ):
    with patch.object(sys, 'platform', 'win32'):
        env = scalene.scalene_preload.ScalenePreload.get_preload_environ(args)
        assert args.memory is False
