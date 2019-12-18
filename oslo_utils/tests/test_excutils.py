# Copyright 2012, Red Hat, Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import logging

import fixtures
import mock
from oslotest import base as test_base
from oslotest import moxstubout

from oslo_utils import excutils
from oslo_utils import timeutils


mox = moxstubout.mox


class Fail1(excutils.CausedByException):
    pass


class Fail2(excutils.CausedByException):
    pass


class CausedByTest(test_base.BaseTestCase):

    def test_caused_by_explicit(self):
        e = self.assertRaises(Fail1,
                              excutils.raise_with_cause,
                              Fail1, "I was broken",
                              cause=Fail2("I have been broken"))
        self.assertIsInstance(e.cause, Fail2)
        e_p = e.pformat()
        self.assertIn("I have been broken", e_p)
        self.assertIn("Fail2", e_p)

    def test_caused_by_implicit(self):

        def raises_chained():
            try:
                raise Fail2("I have been broken")
            except Fail2:
                excutils.raise_with_cause(Fail1, "I was broken")

        e = self.assertRaises(Fail1, raises_chained)
        self.assertIsInstance(e.cause, Fail2)
        e_p = e.pformat()
        self.assertIn("I have been broken", e_p)
        self.assertIn("Fail2", e_p)


class SaveAndReraiseTest(test_base.BaseTestCase):

    def test_save_and_reraise_exception_forced(self):

        def _force_reraise():
            try:
                raise IOError("I broke")
            except Exception:
                with excutils.save_and_reraise_exception() as e:
                    e.reraise = False
                e.force_reraise()

        self.assertRaises(IOError, _force_reraise)

    def test_save_and_reraise_exception_capture_reraise(self):

        def _force_reraise():
            try:
                raise IOError("I broke")
            except Exception:
                excutils.save_and_reraise_exception().capture().force_reraise()

        self.assertRaises(IOError, _force_reraise)

    def test_save_and_reraise_exception_capture_not_active(self):
        e = excutils.save_and_reraise_exception()
        self.assertRaises(RuntimeError, e.capture, check=True)

    def test_save_and_reraise_exception_forced_not_active(self):
        e = excutils.save_and_reraise_exception()
        self.assertRaises(RuntimeError, e.force_reraise)
        e = excutils.save_and_reraise_exception()
        e.capture(check=False)
        self.assertRaises(RuntimeError, e.force_reraise)

    def test_save_and_reraise_exception(self):
        e = None
        msg = 'foo'
        try:
            try:
                raise Exception(msg)
            except Exception:
                with excutils.save_and_reraise_exception():
                    pass
        except Exception as _e:
            e = _e

        self.assertEqual(str(e), msg)

    @mock.patch('logging.getLogger')
    def test_save_and_reraise_exception_dropped(self, get_logger_mock):
        logger = get_logger_mock()
        e = None
        msg = 'second exception'
        try:
            try:
                raise Exception('dropped')
            except Exception:
                with excutils.save_and_reraise_exception():
                    raise Exception(msg)
        except Exception as _e:
            e = _e
        self.assertEqual(str(e), msg)
        self.assertTrue(logger.error.called)

    def test_save_and_reraise_exception_no_reraise(self):
        """Test that suppressing the reraise works."""
        try:
            raise Exception('foo')
        except Exception:
            with excutils.save_and_reraise_exception() as ctxt:
                ctxt.reraise = False

    @mock.patch('logging.getLogger')
    def test_save_and_reraise_exception_dropped_no_reraise(self,
                                                           get_logger_mock):
        logger = get_logger_mock()
        e = None
        msg = 'second exception'
        try:
            try:
                raise Exception('dropped')
            except Exception:
                with excutils.save_and_reraise_exception(reraise=False):
                    raise Exception(msg)
        except Exception as _e:
            e = _e
        self.assertEqual(str(e), msg)
        self.assertFalse(logger.error.called)

    def test_save_and_reraise_exception_provided_logger(self):
        fake_logger = mock.MagicMock()
        try:
            try:
                raise Exception('foo')
            except Exception:
                with excutils.save_and_reraise_exception(logger=fake_logger):
                    raise Exception('second exception')
        except Exception:
            pass
        self.assertTrue(fake_logger.error.called)


class ForeverRetryUncaughtExceptionsTest(test_base.BaseTestCase):

    def setUp(self):
        super(ForeverRetryUncaughtExceptionsTest, self).setUp()
        moxfixture = self.useFixture(moxstubout.MoxStubout())
        self.mox = moxfixture.mox

        self.useFixture(fixtures.MockPatch('time.sleep', return_value=None))

        self.mox.StubOutWithMock(logging, 'exception')
        self.mox.StubOutWithMock(timeutils, 'now',
                                 use_mock_anything=True)
        self.mox.StubOutWithMock(self, 'exception_to_raise')

    @excutils.forever_retry_uncaught_exceptions
    def exception_generator(self):
        exc = self.exception_to_raise()
        while exc is not None:
            raise exc

    def exception_to_raise(self):
        return None

    def test_exc_retrier_1exc_gives_1log(self):
        self.exception_to_raise().AndReturn(
            Exception('unexpected %d' % 1))
        logging.exception(mox.In(
            'Unexpected exception occurred %d time(s)' % 1))
        # Timestamp calls that happen after the logging is possibly triggered.
        for timestamp in [0]:
            timeutils.now().AndReturn(timestamp)

        self.exception_to_raise().AndReturn(None)
        self.mox.ReplayAll()
        self.exception_generator()

    def test_exc_retrier_same_10exc_1min_gives_1log(self):
        self.exception_to_raise().AndReturn(
            Exception('unexpected %d' % 1))
        logging.exception(mox.In(
            'Unexpected exception occurred %d time(s)' % 1))
        # Timestamp calls that happen after the logging is possibly triggered.
        for timestamp in [0]:
            timeutils.now().AndReturn(timestamp)

        # By design, the following exception don't get logged because they
        # are within the same minute.
        for i in range(2, 11):
            self.exception_to_raise().AndReturn(
                Exception('unexpected %d' % 1))
            # Timestamp calls that happen before the logging is possibly
            # triggered.
            for timestamp in [i]:
                timeutils.now().AndReturn(timestamp)

        self.exception_to_raise().AndReturn(None)
        self.mox.ReplayAll()
        self.exception_generator()

    def test_exc_retrier_same_2exc_2min_gives_2logs(self):
        self.exception_to_raise().AndReturn(
            Exception('unexpected %d' % 1))
        logging.exception(mox.In(
            'Unexpected exception occurred %d time(s)' % 1))
        # Timestamp calls that happen after the logging is possibly triggered.
        for timestamp in [0]:
            timeutils.now().AndReturn(timestamp)

        self.exception_to_raise().AndReturn(
            Exception('unexpected %d' % 1))
        # Timestamp calls that happen before the logging is possibly triggered.
        for timestamp in [65]:
            timeutils.now().AndReturn(timestamp)
        logging.exception(mox.In(
            'Unexpected exception occurred %d time(s)' % 1))
        # Timestamp calls that happen after the logging is possibly triggered.
        for timestamp in [65, 66]:
            timeutils.now().AndReturn(timestamp)

        self.exception_to_raise().AndReturn(None)
        self.mox.ReplayAll()
        self.exception_generator()

    def test_exc_retrier_same_10exc_2min_gives_2logs(self):
        self.exception_to_raise().AndReturn(
            Exception('unexpected %d' % 1))
        logging.exception(mox.In(
            'Unexpected exception occurred %d time(s)' % 1))
        # Timestamp calls that happen after the logging is possibly triggered.
        for timestamp in [0]:
            timeutils.now().AndReturn(timestamp)

        for ts in [12, 23, 34, 45]:
            self.exception_to_raise().AndReturn(
                Exception('unexpected %d' % 1))
            # Timestamp calls that happen before the logging is possibly
            # triggered.
            for timestamp in [ts]:
                timeutils.now().AndReturn(timestamp)

        # The previous 4 exceptions are counted here

        self.exception_to_raise().AndReturn(
            Exception('unexpected %d' % 1))
        # Timestamp calls that happen before the logging is possibly triggered.
        for timestamp in [106]:
            timeutils.now().AndReturn(timestamp)
        logging.exception(mox.In(
            'Unexpected exception occurred %d time(s)' % 5))
        # Timestamp calls that happen after the logging is possibly triggered.
        for timestamp in [106, 107]:
            timeutils.now().AndReturn(timestamp)

        # Again, the following are not logged due to being within
        # the same minute

        for ts in [117, 128, 139, 150]:

            self.exception_to_raise().AndReturn(
                Exception('unexpected %d' % 1))
            # Timestamp calls that happen before the logging is possibly
            # triggered.
            for timestamp in [ts]:
                timeutils.now().AndReturn(timestamp)

        self.exception_to_raise().AndReturn(None)
        self.mox.ReplayAll()
        self.exception_generator()

    def test_exc_retrier_mixed_4exc_1min_gives_2logs(self):
        # The stop watch will be started, which will consume one timestamp
        # call.

        self.exception_to_raise().AndReturn(
            Exception('unexpected %d' % 1))
        logging.exception(mox.In(
            'Unexpected exception occurred %d time(s)' % 1))
        # Timestamp calls that happen after the logging is possibly triggered.
        for timestamp in [0]:
            timeutils.now().AndReturn(timestamp)

        # By design, this second 'unexpected 1' exception is not counted.  This
        # is likely a rare thing and is a sacrifice for code simplicity.

        self.exception_to_raise().AndReturn(
            Exception('unexpected %d' % 1))
        # Timestamp calls that happen before the logging is possibly triggered.
        # Since the exception will be the same the expiry method will be
        # called, which uses up a timestamp call.
        for timestamp in [5]:
            timeutils.now().AndReturn(timestamp)

        self.exception_to_raise().AndReturn(
            Exception('unexpected %d' % 2))
        logging.exception(mox.In(
            'Unexpected exception occurred %d time(s)' % 1))
        # Timestamp calls that happen after the logging is possibly triggered.
        # The watch should get reset, which uses up two timestamp calls.
        for timestamp in [10, 20]:
            timeutils.now().AndReturn(timestamp)

        self.exception_to_raise().AndReturn(
            Exception('unexpected %d' % 2))
        # Timestamp calls that happen before the logging is possibly triggered.
        # Since the exception will be the same the expiry method will be
        # called, which uses up a timestamp call.
        for timestamp in [25]:
            timeutils.now().AndReturn(timestamp)

        self.exception_to_raise().AndReturn(None)
        self.mox.ReplayAll()
        self.exception_generator()

    def test_exc_retrier_mixed_4exc_2min_gives_2logs(self):

        self.exception_to_raise().AndReturn(
            Exception('unexpected %d' % 1))
        logging.exception(mox.In(
            'Unexpected exception occurred %d time(s)' % 1))
        # Timestamp calls that happen after the logging is possibly triggered.
        for timestamp in [0]:
            timeutils.now().AndReturn(timestamp)

        # Again, this second exception of the same type is not counted
        # for the sake of code simplicity.

        self.exception_to_raise().AndReturn(
            Exception('unexpected %d' % 1))
        # Timestamp calls that happen before the logging is possibly triggered.
        for timestamp in [10]:
            timeutils.now().AndReturn(timestamp)

        # The difference between this and the previous case is the log
        # is also triggered by more than a minute expiring.

        self.exception_to_raise().AndReturn(
            Exception('unexpected %d' % 2))
        logging.exception(mox.In(
            'Unexpected exception occurred %d time(s)' % 1))
        # Timestamp calls that happen after the logging is possibly triggered.
        for timestamp in [100, 105]:
            timeutils.now().AndReturn(timestamp)

        self.exception_to_raise().AndReturn(
            Exception('unexpected %d' % 2))
        # Timestamp calls that happen before the logging is possibly triggered.
        for timestamp in [110]:
            timeutils.now().AndReturn(timestamp)

        self.exception_to_raise().AndReturn(None)
        self.mox.ReplayAll()
        self.exception_generator()

    def test_exc_retrier_mixed_4exc_2min_gives_3logs(self):
        self.exception_to_raise().AndReturn(
            Exception('unexpected %d' % 1))
        logging.exception(mox.In(
            'Unexpected exception occurred %d time(s)' % 1))
        # Timestamp calls that happen after the logging is possibly triggered.
        for timestamp in [0]:
            timeutils.now().AndReturn(timestamp)

        # This time the second 'unexpected 1' exception is counted due
        # to the same exception occurring same when the minute expires.

        self.exception_to_raise().AndReturn(
            Exception('unexpected %d' % 1))
        # Timestamp calls that happen before the logging is possibly triggered.
        for timestamp in [10]:
            timeutils.now().AndReturn(timestamp)

        self.exception_to_raise().AndReturn(
            Exception('unexpected %d' % 1))
        # Timestamp calls that happen before the logging is possibly triggered.
        for timestamp in [100]:
            timeutils.now().AndReturn(timestamp)
        logging.exception(mox.In(
            'Unexpected exception occurred %d time(s)' % 2))
        # Timestamp calls that happen after the logging is possibly triggered.
        for timestamp in [100, 105]:
            timeutils.now().AndReturn(timestamp)

        self.exception_to_raise().AndReturn(
            Exception('unexpected %d' % 2))
        logging.exception(mox.In(
            'Unexpected exception occurred %d time(s)' % 1))
        # Timestamp calls that happen after the logging is possibly triggered.
        for timestamp in [110, 111]:
            timeutils.now().AndReturn(timestamp)

        self.exception_to_raise().AndReturn(None)
        self.mox.ReplayAll()
        self.exception_generator()


class ExceptionFilterTest(test_base.BaseTestCase):

    def _make_filter_func(self, ignore_classes=AssertionError):
        @excutils.exception_filter
        def ignore_exceptions(ex):
            '''Ignore some exceptions F.'''
            return isinstance(ex, ignore_classes)

        return ignore_exceptions

    def _make_filter_method(self, ignore_classes=AssertionError):
        class ExceptionIgnorer(object):
            def __init__(self, ignore):
                self.ignore = ignore

            @excutils.exception_filter
            def ignore_exceptions(self, ex):
                '''Ignore some exceptions M.'''
                return isinstance(ex, self.ignore)

        return ExceptionIgnorer(ignore_classes).ignore_exceptions

    def _make_filter_classmethod(self, ignore_classes=AssertionError):
        class ExceptionIgnorer(object):
            ignore = ignore_classes

            @excutils.exception_filter
            @classmethod
            def ignore_exceptions(cls, ex):
                '''Ignore some exceptions C.'''
                return isinstance(ex, cls.ignore)

        return ExceptionIgnorer.ignore_exceptions

    def _make_filter_staticmethod(self, ignore_classes=AssertionError):
        class ExceptionIgnorer(object):
            @excutils.exception_filter
            @staticmethod
            def ignore_exceptions(ex):
                '''Ignore some exceptions S.'''
                return isinstance(ex, ignore_classes)

        return ExceptionIgnorer.ignore_exceptions

    def test_filter_func_call(self):
        ignore_assertion_error = self._make_filter_func()

        try:
            assert False, "This is a test"
        except Exception as exc:
            ignore_assertion_error(exc)

    def test_raise_func_call(self):
        ignore_assertion_error = self._make_filter_func()

        try:
            raise RuntimeError
        except Exception as exc:
            self.assertRaises(RuntimeError, ignore_assertion_error, exc)

    def test_raise_previous_func_call(self):
        ignore_assertion_error = self._make_filter_func()

        try:
            raise RuntimeError
        except Exception as exc1:
            try:
                raise RuntimeError
            except Exception as exc2:
                self.assertIsNot(exc1, exc2)
            raised = self.assertRaises(RuntimeError,
                                       ignore_assertion_error,
                                       exc1)
            self.assertIs(exc1, raised)

    def test_raise_previous_after_filtered_func_call(self):
        ignore_assertion_error = self._make_filter_func()

        try:
            raise RuntimeError
        except Exception as exc1:
            try:
                assert False, "This is a test"
            except Exception:
                pass
            self.assertRaises(RuntimeError, ignore_assertion_error, exc1)

    def test_raise_other_func_call(self):
        @excutils.exception_filter
        def translate_exceptions(ex):
            raise RuntimeError

        try:
            assert False, "This is a test"
        except Exception as exc:
            self.assertRaises(RuntimeError, translate_exceptions, exc)

    def test_filter_func_context_manager(self):
        ignore_assertion_error = self._make_filter_func()

        with ignore_assertion_error:
            assert False, "This is a test"

    def test_raise_func_context_manager(self):
        ignore_assertion_error = self._make_filter_func()

        def try_runtime_err():
            with ignore_assertion_error:
                raise RuntimeError

        self.assertRaises(RuntimeError, try_runtime_err)

    def test_raise_other_func_context_manager(self):
        @excutils.exception_filter
        def translate_exceptions(ex):
            raise RuntimeError

        def try_assertion():
            with translate_exceptions:
                assert False, "This is a test"

        self.assertRaises(RuntimeError, try_assertion)

    def test_noexc_func_context_manager(self):
        ignore_assertion_error = self._make_filter_func()

        with ignore_assertion_error:
            pass

    def test_noexc_nocall_func_context_manager(self):
        @excutils.exception_filter
        def translate_exceptions(ex):
            raise RuntimeError

        with translate_exceptions:
            pass

    def test_func_docstring(self):
        ignore_func = self._make_filter_func()
        self.assertEqual('Ignore some exceptions F.', ignore_func.__doc__)

    def test_filter_method_call(self):
        ignore_assertion_error = self._make_filter_method()

        try:
            assert False, "This is a test"
        except Exception as exc:
            ignore_assertion_error(exc)

    def test_raise_method_call(self):
        ignore_assertion_error = self._make_filter_method()

        try:
            raise RuntimeError
        except Exception as exc:
            self.assertRaises(RuntimeError, ignore_assertion_error, exc)

    def test_filter_method_context_manager(self):
        ignore_assertion_error = self._make_filter_method()

        with ignore_assertion_error:
            assert False, "This is a test"

    def test_raise_method_context_manager(self):
        ignore_assertion_error = self._make_filter_method()

        def try_runtime_err():
            with ignore_assertion_error:
                raise RuntimeError

        self.assertRaises(RuntimeError, try_runtime_err)

    def test_method_docstring(self):
        ignore_func = self._make_filter_method()
        self.assertEqual('Ignore some exceptions M.', ignore_func.__doc__)

    def test_filter_classmethod_call(self):
        ignore_assertion_error = self._make_filter_classmethod()

        try:
            assert False, "This is a test"
        except Exception as exc:
            ignore_assertion_error(exc)

    def test_raise_classmethod_call(self):
        ignore_assertion_error = self._make_filter_classmethod()

        try:
            raise RuntimeError
        except Exception as exc:
            self.assertRaises(RuntimeError, ignore_assertion_error, exc)

    def test_filter_classmethod_context_manager(self):
        ignore_assertion_error = self._make_filter_classmethod()

        with ignore_assertion_error:
            assert False, "This is a test"

    def test_raise_classmethod_context_manager(self):
        ignore_assertion_error = self._make_filter_classmethod()

        def try_runtime_err():
            with ignore_assertion_error:
                raise RuntimeError

        self.assertRaises(RuntimeError, try_runtime_err)

    def test_classmethod_docstring(self):
        ignore_func = self._make_filter_classmethod()
        self.assertEqual('Ignore some exceptions C.', ignore_func.__doc__)

    def test_filter_staticmethod_call(self):
        ignore_assertion_error = self._make_filter_staticmethod()

        try:
            assert False, "This is a test"
        except Exception as exc:
            ignore_assertion_error(exc)

    def test_raise_staticmethod_call(self):
        ignore_assertion_error = self._make_filter_staticmethod()

        try:
            raise RuntimeError
        except Exception as exc:
            self.assertRaises(RuntimeError, ignore_assertion_error, exc)

    def test_filter_staticmethod_context_manager(self):
        ignore_assertion_error = self._make_filter_staticmethod()

        with ignore_assertion_error:
            assert False, "This is a test"

    def test_raise_staticmethod_context_manager(self):
        ignore_assertion_error = self._make_filter_staticmethod()

        def try_runtime_err():
            with ignore_assertion_error:
                raise RuntimeError

        self.assertRaises(RuntimeError, try_runtime_err)

    def test_staticmethod_docstring(self):
        ignore_func = self._make_filter_staticmethod()
        self.assertEqual('Ignore some exceptions S.', ignore_func.__doc__)
