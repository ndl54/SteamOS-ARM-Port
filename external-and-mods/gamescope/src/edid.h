#pragma once

#include <span>
#include <cstdint>
#include <optional>
#include <vector>

namespace gamescope
{
    struct BackendConnectorHDRInfo;

    struct EdidModeInfo
    {
        uint32_t clockKHz = 0;
        uint32_t hdisplay = 0;
        uint32_t hsyncStart = 0;
        uint32_t hsyncEnd = 0;
        uint32_t htotal = 0;
        uint32_t vdisplay = 0;
        uint32_t vsyncStart = 0;
        uint32_t vsyncEnd = 0;
        uint32_t vtotal = 0;
        uint32_t physicalWidthMm = 0;
        uint32_t physicalHeightMm = 0;
        bool hsyncPositive = false;
        bool vsyncPositive = false;
    };

    const char *GetPatchedEdidPath();
    void WritePatchedEdid( std::span<const uint8_t> pEdid, const BackendConnectorHDRInfo &hdrInfo, bool bRotate );
    std::vector<uint8_t> GenerateSimpleEdid( uint32_t uWidth, uint32_t uHeight );
    std::vector<uint8_t> GenerateSimpleEdid( const EdidModeInfo &mode );
    const char *EnsureVirtualEdid();

    std::optional<std::vector<uint8_t>> PatchEdid( std::span<const uint8_t> pEdid, const BackendConnectorHDRInfo &hdrInfo, bool bRotate );
}