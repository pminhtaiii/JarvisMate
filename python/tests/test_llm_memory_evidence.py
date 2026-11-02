"""Strict cap/headroom with truthful Windows WDDM process-metric availability."""
import copy
import unittest

from lifemate.llm_training.qualification import GIB,memory_acceptance


class MemoryEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.memory={'operating_cap_bytes':12*GIB,'physical_bytes':12*GIB,'reserved_peak':8*GIB}
        self.nvml={'device_peak_observed_bytes':9*GIB,'device_min_free_observed_bytes':3*GIB,
                   'samples':20,'error':None,'process_peak_observed_bytes':None,
                   'driver_model':'WDDM','own_pid_seen':True}

    def test_wddm_uses_conservative_device_bound_without_faking_process_peak(self):
        before=copy.deepcopy(self.nvml)
        result=memory_acceptance(self.memory,self.nvml)
        self.assertTrue(result['passed'])
        self.assertEqual(result['evidence_mode'],'WDDM_conservative_whole_device_upper_bound')
        self.assertFalse(result['exact_process_peak_available'])
        self.assertEqual(self.nvml,before)
        self.assertIsNone(self.nvml['process_peak_observed_bytes'])

    def test_the_observed_low_headroom_failure_is_never_waived(self):
        self.nvml.update(device_peak_observed_bytes=12*GIB-200_000_000,device_min_free_observed_bytes=200_000_000)
        result=memory_acceptance(self.memory,self.nvml)
        self.assertFalse(result['passed'])
        self.assertIn('whole_device_cap_or_headroom',result['issues'])

    def test_allocator_limit_and_competing_device_usage_remain_separate(self):
        self.memory['reserved_peak']=12*GIB
        self.assertFalse(memory_acceptance(self.memory,self.nvml)['passed'])
        self.memory['reserved_peak']=8*GIB
        self.nvml.update(device_peak_observed_bytes=12*GIB,device_min_free_observed_bytes=0)
        self.assertFalse(memory_acceptance(self.memory,self.nvml)['passed'])

    def test_missing_process_without_verified_wddm_is_unverified(self):
        for change in ({'driver_model':None},{'driver_model':'TCC'},{'own_pid_seen':False}):
            with self.subTest(change=change):
                self.assertFalse(memory_acceptance(self.memory,self.nvml|change)['passed'])

    def test_missing_samples_errors_and_invalid_values_fail_closed(self):
        for change in ({'samples':0},{'error':'lost device'},{'device_peak_observed_bytes':None},
                       {'device_min_free_observed_bytes':-1},{'device_peak_observed_bytes':13*GIB}):
            with self.subTest(change=change):
                self.assertFalse(memory_acceptance(self.memory,self.nvml|change)['passed'])

    def test_native_process_measurement_is_preserved_when_available(self):
        result=memory_acceptance(self.memory,self.nvml|{'driver_model':'TCC','process_peak_observed_bytes':7*GIB})
        self.assertTrue(result['passed'])
        self.assertTrue(result['exact_process_peak_available'])
        self.assertEqual(result['evidence_mode'],'native_process_and_device')


if __name__=='__main__':
    unittest.main()
