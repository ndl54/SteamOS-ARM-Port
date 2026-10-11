#include <catch2/catch_test_macros.hpp>

#include "surface_format_utils.hpp"

#include <array>
#include <cstdint>
#include <vector>

using namespace GamescopeWSILayer::SurfaceFormatUtils;

namespace {

  constexpr std::array<VkSurfaceFormatKHR, 3> s_HDRCandidates = {{
    { VK_FORMAT_A2B10G10R10_UNORM_PACK32, VK_COLOR_SPACE_HDR10_ST2084_EXT },
    { VK_FORMAT_A2R10G10B10_UNORM_PACK32, VK_COLOR_SPACE_HDR10_ST2084_EXT },
    { VK_FORMAT_R16G16B16A16_SFLOAT, VK_COLOR_SPACE_EXTENDED_SRGB_LINEAR_EXT },
  }};

}

TEST_CASE("HDR formats are limited by the underlying surface VkFormats", "[wsi][hdr]") {
  const std::array<VkSurfaceFormatKHR, 2> turnipFormats = {{
    { VK_FORMAT_B8G8R8A8_SRGB, VK_COLOR_SPACE_SRGB_NONLINEAR_KHR },
    { VK_FORMAT_A2R10G10B10_UNORM_PACK32, VK_COLOR_SPACE_SRGB_NONLINEAR_KHR },
  }};
  const auto turnipHDRFormats = filterByUnderlyingVkFormat(s_HDRCandidates, turnipFormats);
  REQUIRE(turnipHDRFormats.size() == 1);
  CHECK(turnipHDRFormats[0].format == VK_FORMAT_A2R10G10B10_UNORM_PACK32);

  const std::array<VkSurfaceFormatKHR, 3> amdFormats = {{
    { VK_FORMAT_A2B10G10R10_UNORM_PACK32, VK_COLOR_SPACE_SRGB_NONLINEAR_KHR },
    { VK_FORMAT_A2R10G10B10_UNORM_PACK32, VK_COLOR_SPACE_SRGB_NONLINEAR_KHR },
    { VK_FORMAT_R16G16B16A16_SFLOAT, VK_COLOR_SPACE_SRGB_NONLINEAR_KHR },
  }};
  const auto amdHDRFormats = filterByUnderlyingVkFormat(s_HDRCandidates, amdFormats);
  REQUIRE(amdHDRFormats.size() == s_HDRCandidates.size());
  for (size_t i = 0; i < s_HDRCandidates.size(); i++)
    CHECK(amdHDRFormats[i].format == s_HDRCandidates[i].format);
}

TEST_CASE("appending surface formats follows Vulkan enumeration semantics", "[wsi][hdr]") {
  const std::array<VkSurfaceFormatKHR, 1> underlying = {{
    { VK_FORMAT_B8G8R8A8_SRGB, VK_COLOR_SPACE_SRGB_NONLINEAR_KHR },
  }};
  const std::array<VkSurfaceFormatKHR, 2> extras = {{
    s_HDRCandidates[0],
    s_HDRCandidates[1],
  }};
  auto query = [&](uint32_t* pCount, VkSurfaceFormatKHR* pFormats) {
    if (!pFormats) {
      *pCount = uint32_t(underlying.size());
      return VK_SUCCESS;
    }
    const uint32_t written = std::min(*pCount, uint32_t(underlying.size()));
    for (uint32_t i = 0; i < written; i++)
      pFormats[i] = underlying[i];
    *pCount = written;
    return written == underlying.size() ? VK_SUCCESS : VK_INCOMPLETE;
  };

  uint32_t count = 0;
  CHECK(append(query, extras, &count, static_cast<VkSurfaceFormatKHR*>(nullptr)) == VK_SUCCESS);
  CHECK(count == 3);

  std::array<VkSurfaceFormatKHR, 2> formats = {};
  count = uint32_t(formats.size());
  CHECK(append(query, extras, &count, formats.data()) == VK_INCOMPLETE);
  REQUIRE(count == formats.size());
  CHECK(formats[0].format == underlying[0].format);
  CHECK(formats[1].format == extras[0].format);
}

TEST_CASE("VkSurfaceFormat2KHR output headers remain application-owned", "[wsi][hdr]") {
  const std::array<VkSurfaceFormat2KHR, 1> underlying = {{
    { VK_STRUCTURE_TYPE_SURFACE_FORMAT_2_KHR, nullptr,
      { VK_FORMAT_B8G8R8A8_SRGB, VK_COLOR_SPACE_SRGB_NONLINEAR_KHR } },
  }};
  const std::array<VkSurfaceFormat2KHR, 1> extras = {{
    { VK_STRUCTURE_TYPE_SURFACE_FORMAT_2_KHR, nullptr,
      { VK_FORMAT_A2R10G10B10_UNORM_PACK32, VK_COLOR_SPACE_HDR10_ST2084_EXT } },
  }};
  auto query = [&](uint32_t* pCount, VkSurfaceFormat2KHR* pFormats) {
    if (!pFormats) {
      *pCount = uint32_t(underlying.size());
      return VK_SUCCESS;
    }
    pFormats[0].surfaceFormat = underlying[0].surfaceFormat;
    *pCount = 1;
    return VK_SUCCESS;
  };

  int sentinel = 0;
  std::array<VkSurfaceFormat2KHR, 2> formats = {{
    { VK_STRUCTURE_TYPE_SURFACE_FORMAT_2_KHR, nullptr, {} },
    { VK_STRUCTURE_TYPE_SURFACE_FORMAT_2_KHR, &sentinel, {} },
  }};
  uint32_t count = uint32_t(formats.size());
  CHECK(append(query, extras, &count, formats.data()) == VK_SUCCESS);
  REQUIRE(count == formats.size());
  CHECK(formats[1].sType == VK_STRUCTURE_TYPE_SURFACE_FORMAT_2_KHR);
  CHECK(formats[1].pNext == &sentinel);
  CHECK(formats[1].surfaceFormat.format == extras[0].surfaceFormat.format);
}

TEST_CASE("temporary VkSurfaceFormat2KHR queries have valid output headers", "[wsi][hdr]") {
  unsigned outputQueries = 0;
  auto query = [&](uint32_t* pCount, VkSurfaceFormat2KHR* pFormats) {
    if (!pFormats) {
      *pCount = 1;
      return VK_SUCCESS;
    }
    CHECK(pFormats[0].sType == VK_STRUCTURE_TYPE_SURFACE_FORMAT_2_KHR);
    CHECK(pFormats[0].pNext == nullptr);
    pFormats[0].surfaceFormat = {
      VK_FORMAT_A2R10G10B10_UNORM_PACK32,
      VK_COLOR_SPACE_SRGB_NONLINEAR_KHR,
    };
    *pCount = 1;
    outputQueries++;
    return outputQueries == 1 ? VK_INCOMPLETE : VK_SUCCESS;
  };

  std::vector<VkSurfaceFormat2KHR> formats;
  CHECK(enumerate(query, formats) == VK_SUCCESS);
  REQUIRE(formats.size() == 1);
  CHECK(outputQueries == 2);
  CHECK(formats[0].surfaceFormat.format == VK_FORMAT_A2R10G10B10_UNORM_PACK32);
}
