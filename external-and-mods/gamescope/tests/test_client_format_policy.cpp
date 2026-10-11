#include <catch2/catch_test_macros.hpp>

#include "ClientFormatPolicy.h"

using namespace gamescope;

TEST_CASE("client modifier advertisement keeps the backend intersection by default", "[vulkan][dmabuf]")
{
    REQUIRE_FALSE( ShouldAdvertiseSampleableClientModifier( false, false, true, false ) );
    REQUIRE( ShouldAdvertiseSampleableClientModifier( false, false, true, true ) );
    REQUIRE( ShouldAdvertiseSampleableClientModifier( false, false, false, false ) );
}

TEST_CASE("sampleable-client opt-in bypasses only the backend advertisement filter", "[vulkan][dmabuf]")
{
    REQUIRE( ShouldAdvertiseSampleableClientModifier( false, true, true, false ) );
    REQUIRE( ShouldAdvertiseSampleableClientModifier( true, false, true, false ) );
}
