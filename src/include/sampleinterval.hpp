#pragma once
#include <random>

template <uint64_t SAMPLE_INTERVAL>
class SampleInterval {
public:

    SampleInterval() :
        _gen(_rd()),
        _dis(0, 2 * SAMPLE_INTERVAL - 1),
        _sampleInterval (_dis(_gen)),
        _increments (0),
        _decrements (0)
    {}

    // resets the interval if we've crossed the interval threshold,
    // returning the previous interval
    uint64_t decrement(uint64_t sample) {
        _decrements += sample;
        if (_decrements >= _increments + _sampleInterval) {
            _decrements -= _sampleInterval;
            auto prevSampleInterval = _sampleInterval;
            _sampleInterval = _dis(_gen);
            return prevSampleInterval;
        }
        return 0;
    }

    // resets the interval if we've crossed the interval threshold,
    // returning the previous interval
    uint64_t increment(uint64_t sample) {
        _increments += sample;
        if (_increments >=  _decrements + _sampleInterval) {
            _increments -= _sampleInterval;
            auto prevSampleInterval = _sampleInterval;
            _sampleInterval = _dis(_gen);
            return prevSampleInterval;;
        }
        return 0;
    }

private:

    std::random_device _rd;
    std::mt19937_64 _gen;
    std::uniform_int_distribution<> _dis;
    uint64_t _sampleInterval;
    uint64_t _increments;
    uint64_t _decrements;
};
