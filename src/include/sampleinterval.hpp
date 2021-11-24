#pragma once
#include <random>

/**
 * @brief "triggers" samples periodically when |increments-decrements| > SAMPLE_INTERVAL
 * 
 * @tparam SAMPLE_INTERVAL 
 */

template <uint64_t SAMPLE_INTERVAL>
class SampleInterval {
public:
    /**
     * @brief Construct a new SampleInterval object
     * 
     * intervals are randomized with a mean of SAMPLE_INTERVAL
     */
    SampleInterval() :
        _gen(_rd()),
        _dis(0, 2 * SAMPLE_INTERVAL - 1),
        _sampleInterval (_dis(_gen)),
        _increments (0),
        _decrements (0)
    {}

    /**
     * @brief decrement by the sample amount, triggering an interval reset when we cross the threshold
     * 
     * @param sample the amount to decrement the sample interval by 
     * @return uint64_t the previous sample interval if we crossed it; 0 otherwise
     */
    uint64_t decrement(uint64_t sample) {
        _decrements += sample;
        if (_decrements >= _increments + _sampleInterval) {
            _decrements = 0;
            auto prevSampleInterval = _sampleInterval;
            _sampleInterval = _dis(_gen);
            return prevSampleInterval;
        }
        return 0;
    }

    /**
     * @brief increment by the sample amount, triggering an interval reset when we cross the threshold
     * 
     * @param sample the amount to decrement the sample interval by 
     * @return uint64_t the previous sample interval if we crossed it; 0 otherwise
     */
    uint64_t increment(uint64_t sample) {
        _increments += sample;
        if (_increments >=  _decrements + _sampleInterval) {
            _increments = 0;
            auto prevSampleInterval = _sampleInterval;
            _sampleInterval = _dis(_gen);
            return prevSampleInterval;;
        }
        return 0;
    }

private:

    std::random_device _rd; /// random device for generating random intervals
    std::mt19937_64 _gen;  /// random number generator
    std::uniform_int_distribution<> _dis; /// distribution for generating random intervals
    uint64_t _sampleInterval; /// the current sample interval
    uint64_t _increments; /// the number of increments since the last sample interval reset
    uint64_t _decrements; /// the number of decrements since the last sample interval reset
};
