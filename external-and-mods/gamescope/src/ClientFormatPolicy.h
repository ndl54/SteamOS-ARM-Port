#pragma once

namespace gamescope
{
    // Client buffers only need to be sampleable by the Vulkan compositor.
    // Backends may impose a stricter modifier set for direct scanout. Keep
    // that historical intersection unless a platform explicitly opts in.
    constexpr bool ShouldAdvertiseSampleableClientModifier(
        bool bAllowDeferredBackend,
        bool bExposeClientSampleableFormats,
        bool bBackendUsesModifiers,
        bool bBackendSupportsModifier )
    {
        return bAllowDeferredBackend ||
            bExposeClientSampleableFormats ||
            !bBackendUsesModifiers ||
            bBackendSupportsModifier;
    }
}
