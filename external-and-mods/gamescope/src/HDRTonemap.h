#pragma once

#include "color_helpers.h"

namespace gamescope
{
    // PQ tops out at 10000 nits; titles are seen reporting sentinel or
    // wrong-unit mastering values (e.g. 6.58e6).
    constexpr bool TonemapNitsPlausible( float flNits )
    {
        return flNits > 0.0f && flNits <= 10000.0f;
    }

    // Black stays zero: the EETF is non-finite below a positive source black.
    constexpr tonemap_info_t AppTonemapSourceInfo(
        float flMaxCLLNits,
        float flMasteringMaxNits )
    {
        tonemap_info_t info{};
        if ( TonemapNitsPlausible( flMaxCLLNits ) )
            info.flWhitePointNits = flMaxCLLNits;
        else if ( TonemapNitsPlausible( flMasteringMaxNits ) )
            info.flWhitePointNits = flMasteringMaxNits;
        return info;
    }

    // Peaks at or below the display white hit the EETF ks == 1 singularity
    // and need no compression anyway.
    constexpr bool ShouldDefaultTonemapOperator(
        bool bSynthesizedSource,
        bool bOperatorAtomSet,
        ETonemapOperator eOperator,
        float flSourceWhiteNits,
        float flDisplayWhiteNits )
    {
        return bSynthesizedSource && !bOperatorAtomSet &&
            eOperator == ETonemapOperator_None &&
            flSourceWhiteNits > flDisplayWhiteNits;
    }
}
