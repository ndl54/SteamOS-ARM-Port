#pragma once

#include "../color_helpers.h"

#include <cstdint>

namespace gamescope
{
    // Output LUT eligibility guarantees that every layer is SDR.
    constexpr bool DrmHdrOutputRequiresVulkanComposition(
        bool bOutputHDREnabled,
        bool bSupportsHardwareColorManagement,
        EOTF eOutputEncodingEOTF,
        uint32_t uLayerCount,
        bool bBaseLayerIsHDR10PQ,
        bool bOutputLuts )
    {
        if ( !bOutputHDREnabled || bSupportsHardwareColorManagement || bOutputLuts )
            return false;

        return eOutputEncodingEOTF != EOTF_PQ ||
            uLayerCount != 1 ||
            !bBaseLayerIsHDR10PQ;
    }
}
