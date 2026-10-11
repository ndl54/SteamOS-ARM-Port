#include <catch2/catch_test_macros.hpp>
#include <catch2/catch_approx.hpp>

#include "Backends/DRMComposition.h"
#include "HDRGamma22.h"
#include "HDRTonemap.h"

#include <cmath>

using namespace gamescope;

TEST_CASE("Gamma 2.2 HDR cannot direct scan without hardware color management", "[drm][hdr]")
{
    // Regression: the old DRM path allowed this exact single-PQ-layer case to
    // direct scan, bypassing the PQ-to-native-Gamma-2.2 Vulkan transform.
    REQUIRE( DrmHdrOutputRequiresVulkanComposition( true, false, EOTF_Gamma22, 1, true, false ) );

    REQUIRE_FALSE( DrmHdrOutputRequiresVulkanComposition( true, true, EOTF_Gamma22, 1, true, false ) );
    REQUIRE_FALSE( DrmHdrOutputRequiresVulkanComposition( true, false, EOTF_PQ, 1, true, false ) );
    REQUIRE_FALSE( DrmHdrOutputRequiresVulkanComposition( false, false, EOTF_Gamma22, 1, true, false ) );

    REQUIRE( DrmHdrOutputRequiresVulkanComposition( true, false, EOTF_PQ, 2, true, false ) );
    REQUIRE( DrmHdrOutputRequiresVulkanComposition( true, false, EOTF_PQ, 1, false, false ) );
}

TEST_CASE("SDR output LUTs allow scanout while HDR output is enabled", "[drm][hdr]")
{
    REQUIRE_FALSE( DrmHdrOutputRequiresVulkanComposition( true, false, EOTF_Gamma22, 1, false, true ) );
    REQUIRE_FALSE( DrmHdrOutputRequiresVulkanComposition( true, false, EOTF_Gamma22, 2, false, true ) );
    REQUIRE( DrmHdrOutputRequiresVulkanComposition( true, false, EOTF_Gamma22, 1, false, false ) );
    REQUIRE( DrmHdrOutputRequiresVulkanComposition( true, false, EOTF_Gamma22, 1, true, false ) );
}

TEST_CASE("Gamma 2.2 HDR scales SDR white against panel peak", "[color][hdr]")
{
    REQUIRE( Gamma22HdrSDRInputScale( true, EOTF_Gamma22, 203.0f, 650.0f ) ==
        Catch::Approx( 203.0f / 650.0f ) );
    REQUIRE( Gamma22HdrSDRInputScale( true, EOTF_Gamma22, 500.0f, 650.0f ) ==
        Catch::Approx( 500.0f / 650.0f ) );
    REQUIRE( Gamma22HdrSDRInputScale( true, EOTF_Gamma22, 900.0f, 650.0f ) == 1.0f );

    REQUIRE( Gamma22HdrSDRInputScale( false, EOTF_Gamma22, 203.0f, 650.0f ) == 1.0f );
    REQUIRE( Gamma22HdrSDRInputScale( true, EOTF_PQ, 203.0f, 650.0f ) == 1.0f );
    REQUIRE( Gamma22HdrSDRInputScale( true, EOTF_Gamma22, 0.0f, 650.0f ) == 1.0f );
    REQUIRE( Gamma22HdrSDRInputScale( true, EOTF_Gamma22, 203.0f, 0.0f ) == 1.0f );
}

TEST_CASE("Gamma 2.2 HDR mode participates in LUT cache currentness", "[color][hdr]")
{
    REQUIRE_FALSE( ColorMgmtLutsAreCurrent( true, true, true, false ) );
    REQUIRE_FALSE( ColorMgmtLutsAreCurrent( true, true, false, true ) );
    REQUIRE( ColorMgmtLutsAreCurrent( true, true, true, true ) );
    REQUIRE( ColorMgmtLutsAreCurrent( true, true, false, false ) );

    REQUIRE_FALSE( ColorMgmtLutsAreCurrent( false, true, false, false ) );
    REQUIRE_FALSE( ColorMgmtLutsAreCurrent( true, false, false, false ) );
}

TEST_CASE("Gamma 2.2 SDR white is ignored while HDR is off", "[color][hdr]")
{
    REQUIRE( Gamma22HdrSDRInputScale( false, EOTF_Gamma22, 203.0f, 650.0f ) == 1.0f );
    REQUIRE( Gamma22HdrSDRInputScale( false, EOTF_Gamma22, 500.0f, 650.0f ) == 1.0f );
}

TEST_CASE("Gamma 2.2 SDR white is only scaled against HDR content", "[color][hdr]")
{
    REQUIRE_FALSE( ShouldScaleGamma22SDRWhite( true, false, true ) );

    REQUIRE( ShouldScaleGamma22SDRWhite( true, true, true ) );
    REQUIRE_FALSE( ShouldScaleGamma22SDRWhite( false, true, true ) );
    REQUIRE_FALSE( ShouldScaleGamma22SDRWhite( true, true, false ) );
}

TEST_CASE("App HDR metadata fallback sanitizes implausible values", "[color][hdr]")
{
    REQUIRE( AppTonemapSourceInfo( 2000.0f, 6.583e6f ).flWhitePointNits == 2000.0f );
    REQUIRE( AppTonemapSourceInfo( 0.0f, 4000.0f ).flWhitePointNits == 4000.0f );
    REQUIRE_FALSE( AppTonemapSourceInfo( 0.0f, 6.583e6f ).BIsValid() );
    REQUIRE_FALSE( AppTonemapSourceInfo( 0.0f, 0.0f ).BIsValid() );
    REQUIRE( AppTonemapSourceInfo( 2000.0f, 4000.0f ).flBlackPointNits == 0.0f );
}

TEST_CASE("Tonemap operator defaults only for compressing synthesized sources", "[color][hdr]")
{
    REQUIRE( ShouldDefaultTonemapOperator( true, false, ETonemapOperator_None, 2000.0f, 650.0f ) );

    REQUIRE_FALSE( ShouldDefaultTonemapOperator( true, false, ETonemapOperator_None, 650.0f, 650.0f ) );
    REQUIRE_FALSE( ShouldDefaultTonemapOperator( true, false, ETonemapOperator_None, 400.0f, 650.0f ) );
    REQUIRE_FALSE( ShouldDefaultTonemapOperator( false, false, ETonemapOperator_None, 2000.0f, 650.0f ) );
    REQUIRE_FALSE( ShouldDefaultTonemapOperator( true, true, ETonemapOperator_None, 2000.0f, 650.0f ) );
    REQUIRE_FALSE( ShouldDefaultTonemapOperator( true, false, ETonemapOperator_EETF2390_Luma, 2000.0f, 650.0f ) );
}

TEST_CASE("Synthesized tonemap configs keep the EETF finite", "[color][hdr]")
{
    eetf_2390_t eetf;
    eetf.init( AppTonemapSourceInfo( 2000.0f, 0.0f ), tonemap_info_t{ 0.0f, 650.0f } );
    for ( float flNits : { 0.001f, 0.01f, 1.0f, 100.0f, 650.0f, 2000.0f, 3000.0f } )
        REQUIRE( std::isfinite( eetf.apply_max_rgb( glm::vec3( flNits ) ).r ) );
}
