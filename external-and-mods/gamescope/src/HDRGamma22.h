#pragma once

#include "color_helpers.h"

#include <limits>

namespace gamescope
{
    constexpr bool ColorMgmtLutsAreCurrent(
        bool bColorMgmtConfigCurrent,
        bool bLutsInitialized,
        bool bCachedScaleSDRWhite,
        bool bScaleSDRWhite )
    {
        return bColorMgmtConfigCurrent && bLutsInitialized &&
            bCachedScaleSDRWhite == bScaleSDRWhite;
    }

    // The output stays in HDR with SDR content, so key on the focused app. An
    // outgoing HDR base still composites through the fade.
    constexpr bool ShouldScaleGamma22SDRWhite(
        bool bOutputHDREnabled,
        bool bAppWantsHDR,
        bool bOutputIsHDRG22 )
    {
        return bOutputHDREnabled && bAppWantsHDR && bOutputIsHDRG22;
    }

    // PQ encodes SDR white in its transfer function; Gamma 2.2 does not.
    constexpr float Gamma22HdrSDRInputScale(
        bool bScaleSDRWhite,
        EOTF eOutputEncodingEOTF,
        float flSDRWhiteNits,
        float flPanelPeakNits )
    {
        if ( !bScaleSDRWhite || eOutputEncodingEOTF != EOTF_Gamma22 ||
             !( flSDRWhiteNits >= 1.0f ) ||
             !( flSDRWhiteNits <= std::numeric_limits<float>::max() ) ||
             !( flPanelPeakNits >= 1.0f ) ||
             !( flPanelPeakNits <= std::numeric_limits<float>::max() ) )
        {
            return 1.0f;
        }

        const float flClampedSDRWhiteNits = flSDRWhiteNits < flPanelPeakNits
            ? flSDRWhiteNits
            : flPanelPeakNits;
        return flClampedSDRWhiteNits / flPanelPeakNits;
    }
}
