#include <catch2/catch_test_macros.hpp>
#include <catch2/catch_message.hpp>

#include "backend.h"
#include "edid.h"

#include <cmath>
#include <cstdint>

extern "C"
{
#include "libdisplay-info/cta.h"
#include "libdisplay-info/edid.h"
#include "libdisplay-info/info.h"
}

using namespace gamescope;

static const EdidModeInfo k_Odin3Mode
{
    .clockKHz = 267843,
    .hdisplay = 1080,
    .hsyncStart = 1104,
    .hsyncEnd = 1105,
    .htotal = 1129,
    .vdisplay = 1920,
    .vsyncStart = 1948,
    .vsyncEnd = 1949,
    .vtotal = 1977,
    .physicalWidthMm = 136,
    .physicalHeightMm = 68,
    .hsyncPositive = true,
    .vsyncPositive = true,
};

TEST_CASE("Synthetic EDID represents the complete DRM mode", "[edid]")
{
    const EdidModeInfo expected = k_Odin3Mode;

    const std::vector<uint8_t> edid = GenerateSimpleEdid( expected );
    REQUIRE( edid.size() == 256 );

    for ( size_t block = 0; block < edid.size() / 128; block++ )
    {
        uint8_t checksum = 0;
        for ( size_t i = 0; i < 128; i++ )
            checksum += edid[block * 128 + i];
        REQUIRE( checksum == 0 );
    }

    const uint8_t *dtd = &edid[0x36];
    const uint32_t pixelClockKHz = ( dtd[0] | ( dtd[1] << 8 ) ) * 10;
    const uint32_t hactive = dtd[2] | ( ( dtd[4] >> 4 ) << 8 );
    const uint32_t hblank = dtd[3] | ( ( dtd[4] & 0xf ) << 8 );
    const uint32_t vactive = dtd[5] | ( ( dtd[7] >> 4 ) << 8 );
    const uint32_t vblank = dtd[6] | ( ( dtd[7] & 0xf ) << 8 );
    const double refreshHz = ( pixelClockKHz * 1000.0 ) /
        ( ( hactive + hblank ) * ( vactive + vblank ) );

    CHECK( hactive == expected.hdisplay );
    CHECK( vactive == expected.vdisplay );
    CHECK( std::abs( static_cast<int64_t>( pixelClockKHz ) - expected.clockKHz ) <= 5 );
    CHECK( std::fabs( refreshHz - 120.0 ) < 0.01 );
    CHECK( edid[0x15] == 14 );
    CHECK( edid[0x16] == 7 );
    CHECK( ( edid[0x18] & 0x01 ) == 0 );
    CHECK( edid[128] == 0x02 );
    CHECK( edid[130] == 4 );

    di_info *info = di_info_parse_edid( edid.data(), edid.size() );
    REQUIRE( info != nullptr );
    di_info_destroy( info );
}

TEST_CASE("Synthetic EDID advertises sRGB chromaticity", "[edid]")
{
    const std::vector<uint8_t> edid = GenerateSimpleEdid( k_Odin3Mode );
    REQUIRE( !edid.empty() );

    di_info *info = di_info_parse_edid( edid.data(), edid.size() );
    REQUIRE( info != nullptr );

    const di_edid_chromaticity_coords *chroma =
        di_edid_get_chromaticity_coords( di_info_get_edid( info ) );
    REQUIRE( chroma != nullptr );
    CHECK( std::fabs( chroma->red_x - 0.640f ) < 0.002f );
    CHECK( std::fabs( chroma->red_y - 0.330f ) < 0.002f );
    CHECK( std::fabs( chroma->green_x - 0.300f ) < 0.002f );
    CHECK( std::fabs( chroma->green_y - 0.600f ) < 0.002f );
    CHECK( std::fabs( chroma->blue_x - 0.150f ) < 0.002f );
    CHECK( std::fabs( chroma->blue_y - 0.060f ) < 0.002f );
    CHECK( std::fabs( chroma->white_x - 0.3127f ) < 0.002f );
    CHECK( std::fabs( chroma->white_y - 0.3290f ) < 0.002f );

    di_info_destroy( info );
}

TEST_CASE("Synthetic EDID treats unencodable physical size as unknown", "[edid]")
{
    EdidModeInfo mode = k_Odin3Mode;
    mode.physicalWidthMm = 5000;

    const std::vector<uint8_t> edid = GenerateSimpleEdid( mode );
    REQUIRE( !edid.empty() );

    const uint8_t *dtd = &edid[0x36];
    CHECK( edid[0x15] == 0 );
    CHECK( edid[0x16] == 0 );
    CHECK( dtd[12] == 0 );
    CHECK( dtd[13] == 0 );
    CHECK( dtd[14] == 0 );
}

TEST_CASE("HDR patching inserts valid metadata into the synthetic CTA", "[edid][hdr]")
{
    const std::vector<uint8_t> edid = GenerateSimpleEdid( k_Odin3Mode );
    REQUIRE( !edid.empty() );

    BackendConnectorHDRInfo hdrInfo{};
    hdrInfo.bExposeHDRSupport = true;
    hdrInfo.eOutputEncodingEOTF = EOTF_Gamma22;
    hdrInfo.uMaxContentLightLevel = 650;
    hdrInfo.uMaxFrameAverageLuminance = 650;
    REQUIRE( hdrInfo.ShouldPatchEDID() );

    const std::optional<std::vector<uint8_t>> patched = PatchEdid( edid, hdrInfo, false );
    REQUIRE( patched.has_value() );
    REQUIRE( patched->size() == edid.size() );

    for ( size_t block = 0; block < patched->size() / 128; block++ )
    {
        uint8_t checksum = 0;
        for ( size_t i = 0; i < 128; i++ )
            checksum += ( *patched )[block * 128 + i];
        REQUIRE( checksum == 0 );
    }

    // The descriptor offset must sit past the inserted 7-byte block, or the
    // block would be misread as a detailed timing.
    CHECK( ( *patched )[128 + 2] == 4 + 7 );

    di_info *info = di_info_parse_edid( patched->data(), patched->size() );
    REQUIRE( info != nullptr );

    const di_cta_hdr_static_metadata_block *hdrBlock = nullptr;
    const di_edid_ext *const *exts = di_edid_get_extensions( di_info_get_edid( info ) );
    for ( ; *exts != nullptr; exts++ )
    {
        const di_edid_cta *cta = di_edid_ext_get_cta( *exts );
        if ( !cta )
            continue;

        const di_cta_data_block *const *blocks = di_edid_cta_get_data_blocks( cta );
        for ( ; *blocks != nullptr; blocks++ )
        {
            if ( di_cta_data_block_get_tag( *blocks ) == DI_CTA_DATA_BLOCK_HDR_STATIC_METADATA )
                hdrBlock = di_cta_data_block_get_hdr_static_metadata( *blocks );
        }
    }

    REQUIRE( hdrBlock != nullptr );
    CHECK( hdrBlock->eotfs->pq );
    // The CTA luminance encoding is coarse; just require the right ballpark.
    CHECK( hdrBlock->desired_content_max_luminance > 550.0f );
    CHECK( hdrBlock->desired_content_max_luminance < 800.0f );

    di_info_destroy( info );
}

TEST_CASE("Synthetic EDID rejects timings EDID cannot encode", "[edid]")
{
    EdidModeInfo mode = k_Odin3Mode;
    REQUIRE( !GenerateSimpleEdid( mode ).empty() );

    mode = k_Odin3Mode;
    mode.hdisplay = 4096;
    REQUIRE( GenerateSimpleEdid( mode ).empty() );

    mode = k_Odin3Mode;
    mode.clockKHz = 0;
    REQUIRE( GenerateSimpleEdid( mode ).empty() );

    mode = k_Odin3Mode;
    mode.hsyncStart = mode.hdisplay - 1;
    REQUIRE( GenerateSimpleEdid( mode ).empty() );

    mode = k_Odin3Mode;
    mode.htotal = mode.hdisplay;
    REQUIRE( GenerateSimpleEdid( mode ).empty() );
}

TEST_CASE("Synthetic EDID clamps sync porches it cannot describe", "[edid]")
{
    EdidModeInfo mode = k_Odin3Mode;
    mode.vsyncStart = mode.vdisplay + 412;
    mode.vsyncEnd = mode.vsyncStart + 4;
    mode.vtotal = mode.vsyncEnd + 8;

    std::vector<uint8_t> edid = GenerateSimpleEdid( mode );
    REQUIRE( edid.size() == 256 );

    const uint8_t *dtd = &edid[0x36];
    uint32_t vsyncOffset = ( ( dtd[10] >> 4 ) & 0xf ) | ( ( ( dtd[11] >> 2 ) & 0x3 ) << 4 );
    uint32_t vsyncWidth  = ( dtd[10] & 0xf ) | ( ( dtd[11] & 0x3 ) << 4 );
    CHECK( vsyncOffset == 63 );
    CHECK( vsyncWidth == 4 );

    di_info *info = di_info_parse_edid( edid.data(), edid.size() );
    REQUIRE( info != nullptr );
    di_info_destroy( info );

    mode = k_Odin3Mode;
    mode.vsyncEnd = mode.vsyncStart + 64;
    mode.vtotal = mode.vsyncEnd + 1;
    edid = GenerateSimpleEdid( mode );
    REQUIRE( edid.size() == 256 );
    dtd = &edid[0x36];
    vsyncWidth = ( dtd[10] & 0xf ) | ( ( dtd[11] & 0x3 ) << 4 );
    CHECK( vsyncWidth == 63 );
}

TEST_CASE("Synthetic EDID encodes sync timings in the correct DTD bytes", "[edid]")
{
    const std::vector<uint8_t> edid = GenerateSimpleEdid( k_Odin3Mode );
    REQUIRE( edid.size() == 256 );

    const uint8_t *dtd = &edid[0x36];
    const uint32_t hsyncOffset = dtd[8] | ( ( dtd[11] >> 6 ) << 8 );
    const uint32_t hsyncWidth  = dtd[9] | ( ( ( dtd[11] >> 4 ) & 0x3 ) << 8 );
    const uint32_t vsyncOffset = ( ( dtd[10] >> 4 ) & 0xf ) | ( ( ( dtd[11] >> 2 ) & 0x3 ) << 4 );
    const uint32_t vsyncWidth  = ( dtd[10] & 0xf ) | ( ( dtd[11] & 0x3 ) << 4 );

    CHECK( hsyncOffset == k_Odin3Mode.hsyncStart - k_Odin3Mode.hdisplay );
    CHECK( hsyncWidth  == k_Odin3Mode.hsyncEnd - k_Odin3Mode.hsyncStart );
    CHECK( vsyncOffset == k_Odin3Mode.vsyncStart - k_Odin3Mode.vdisplay );
    CHECK( vsyncWidth  == k_Odin3Mode.vsyncEnd - k_Odin3Mode.vsyncStart );
}

TEST_CASE("Pocket EVO synthetic EDID preserves each published mode timing", "[edid]")
{
    struct Timing { uint32_t hz, clock, hfp, vfp; };
    const Timing timings[] = {
        { 60, 355017, 156, 2760 }, { 90, 354715, 156, 1192 },
        { 120, 355017, 156, 412 }, { 144, 354896, 156, 20 },
        { 165, 387933, 98, 20 },
    };
    for ( const auto &t : timings )
    {
        INFO( t.hz );
        EdidModeInfo mode = k_Odin3Mode;
        mode.clockKHz = t.clock;
        mode.hsyncStart = 1080 + t.hfp;
        mode.hsyncEnd = mode.hsyncStart + 1;
        mode.htotal = mode.hsyncEnd + 23;
        mode.vsyncStart = 1920 + t.vfp;
        mode.vsyncEnd = mode.vsyncStart + 1;
        mode.vtotal = mode.vsyncEnd + 15;
        const auto edid = GenerateSimpleEdid( mode );
        REQUIRE( edid.size() == 256 );
        const uint8_t *dtd = &edid[0x36];
        const uint32_t clock = (dtd[0] | (dtd[1] << 8)) * 10;
        const uint32_t htotal = (dtd[2] | ((dtd[4] >> 4) << 8)) +
            (dtd[3] | ((dtd[4] & 15) << 8));
        const uint32_t vtotal = (dtd[5] | ((dtd[7] >> 4) << 8)) +
            (dtd[6] | ((dtd[7] & 15) << 8));
        CHECK( htotal == mode.htotal );
        CHECK( vtotal == mode.vtotal );
        CHECK( std::abs(clock * 1000.0 / (htotal * vtotal) - t.hz) < 0.01 );
        di_info *info = di_info_parse_edid( edid.data(), edid.size() );
        REQUIRE( info != nullptr );
        di_info_destroy( info );
    }
}
