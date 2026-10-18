#pragma once

namespace gamescope
{
	// Discover /sys/class/backlight and keep a writable fd when possible.
	void InitBacklight();

	// 0..1 inclusive. Writes the hardware backlight when we can.
	// Returns true if the hardware (or a software fallback) accepted the change.
	// Nonfinite values are rejected without changing the requested level.
	bool SetBacklightNormalized( float flNorm );

	float GetBacklightNormalized();
	bool HasHardwareBacklight();

	// 1.0 when hardware backlight is driving the panel; otherwise the last
	// requested level so the compositor can dim in the color pipeline.
	float GetSoftwareBacklightGain();

	// Steam Game Mode writes a CARDINAL bit-cast float:
	//   0..1   = normalized
	//   >1     = nits (not percent)
	// Nits require an explicit backlight_max_nits endpoint. No samples or
	// persisted history are calibration. Out-of-range values are rejected.
	// flColorNits is NaN when normalized input has no configured nits range.
	bool ApplySteamBrightnessValue( float flVal, float &flColorNits );

	// Keyboard / hotkey steps. Returns true if the level changed.
	bool StepBacklight( int nDirection );
}
