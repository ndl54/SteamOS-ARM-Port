#include <catch2/catch_test_macros.hpp>

#include "Script/Script.h"

using namespace gamescope;

TEST_CASE("Known-display matching receives connector identity", "[display]")
{
    CScriptScopedLock script;
    script->script( R"(
        gamescope.config.known_displays.test_edidless_panel = {
            pretty_name = "Test EDID-less panel",
            matches = function(display)
                if display.connector == "DSI-1" and
                   display.device_id == "test-device" and
                   display.internal and
                   not display.has_edid then
                    return 6000
                end
                return -1
            end,
        }
        gamescope.config.known_displays.test_model_panel = {
            pretty_name = "Test model-matched panel",
            matches = function(display)
                if display.model == "Gamescope" then
                    return 100
                end
                return -1
            end,
        }
    )" );

    // A synthetic EDID parses with the generic Gamescope identity, so an
    // identity-based profile must outrank a model-based one.
    const GamescopeDisplayLookupInfo panel
    {
        .vendor = "FRG",
        .product = 0x01f4,
        .model = "Gamescope",
        .dataString = "",
        .connector = "DSI-1",
        .deviceId = "test-device",
        .internal = true,
        .hasEdid = false,
    };

    auto match = script.Manager().Gamescope().Config.LookupDisplay( script, panel );
    REQUIRE( match.has_value() );
    CHECK( match->first == "test_edidless_panel" );

    GamescopeDisplayLookupInfo wrongDevice = panel;
    wrongDevice.deviceId = "other-device";
    auto fallback = script.Manager().Gamescope().Config.LookupDisplay( script, wrongDevice );
    REQUIRE( fallback.has_value() );
    CHECK( fallback->first == "test_model_panel" );

    GamescopeDisplayLookupInfo physical = panel;
    physical.model = "Some Panel";
    physical.hasEdid = true;
    CHECK_FALSE( script.Manager().Gamescope().Config.LookupDisplay( script, physical ) );

    GamescopeDisplayLookupInfo external = panel;
    external.internal = false;
    external.model = "Some Panel";
    CHECK_FALSE( script.Manager().Gamescope().Config.LookupDisplay( script, external ) );

    script.Manager().Gamescope().Config.KnownDisplays["test_edidless_panel"] = sol::lua_nil;
    script.Manager().Gamescope().Config.KnownDisplays["test_model_panel"] = sol::lua_nil;
}
