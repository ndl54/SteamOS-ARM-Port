#pragma once

#include <vulkan/vulkan.h>

#include <algorithm>
#include <cstdint>
#include <limits>
#include <vector>

namespace GamescopeWSILayer::SurfaceFormatUtils {

  inline VkFormat getVkFormat(const VkSurfaceFormatKHR& surfaceFormat) {
    return surfaceFormat.format;
  }

  inline VkFormat getVkFormat(const VkSurfaceFormat2KHR& surfaceFormat) {
    return surfaceFormat.surfaceFormat.format;
  }

  inline void prepareForQuery(VkSurfaceFormatKHR&) {
  }

  inline void prepareForQuery(VkSurfaceFormat2KHR& surfaceFormat) {
    surfaceFormat.sType = VK_STRUCTURE_TYPE_SURFACE_FORMAT_2_KHR;
    surfaceFormat.pNext = nullptr;
  }

  template <typename Function, typename OutputArray, typename... Args>
  VkResult enumerate(Function function, OutputArray& output, Args... arguments) {
    for (;;) {
      uint32_t count = 0;
      VkResult result = function(arguments..., &count, nullptr);
      if (result != VK_SUCCESS) {
        output.clear();
        return result;
      }

      output.resize(count);
      for (auto& surfaceFormat : output)
        prepareForQuery(surfaceFormat);

      if (count == 0)
        return VK_SUCCESS;

      result = function(arguments..., &count, output.data());
      if (result == VK_INCOMPLETE)
        continue;
      if (result != VK_SUCCESS) {
        output.clear();
        return result;
      }

      output.resize(count);
      return VK_SUCCESS;
    }
  }

  template <typename CandidateArray, typename UnderlyingArray>
  auto filterByUnderlyingVkFormat(const CandidateArray& candidates, const UnderlyingArray& underlying) {
    using Candidate = typename CandidateArray::value_type;
    std::vector<Candidate> filtered;
    filtered.reserve(candidates.size());

    for (const Candidate& candidate : candidates) {
      const bool supported = std::any_of(
        underlying.begin(),
        underlying.end(),
        [&](const auto& surfaceFormat) {
          return getVkFormat(surfaceFormat) == getVkFormat(candidate);
        });
      if (supported)
        filtered.push_back(candidate);
    }

    return filtered;
  }

  template <typename Output, typename Extra>
  void writeExtra(Output& output, const Extra& extra) {
    output = extra;
  }

  inline void writeExtra(VkSurfaceFormat2KHR& output, const VkSurfaceFormat2KHR& extra) {
    // VkSurfaceFormat2KHR is an output structure supplied by the application.
    // Preserve its sType and pNext chain while filling the result payload.
    output.surfaceFormat = extra.surfaceFormat;
  }

  template <typename Function, typename ExtraArray, typename Output, typename... Args>
  VkResult append(Function function, const ExtraArray& extras, uint32_t* pCount, Output* pOutput, Args... arguments) {
    uint32_t underlyingCount = 0;
    VkResult result = function(arguments..., &underlyingCount, nullptr);
    if (result != VK_SUCCESS)
      return result;

    if (extras.size() > std::numeric_limits<uint32_t>::max() - underlyingCount)
      return VK_ERROR_OUT_OF_HOST_MEMORY;

    const uint32_t totalCount = underlyingCount + uint32_t(extras.size());
    if (!pOutput) {
      *pCount = totalCount;
      return VK_SUCCESS;
    }

    const uint32_t capacity = *pCount;
    uint32_t underlyingWritten = std::min(capacity, underlyingCount);

    if (underlyingWritten > 0) {
      result = function(arguments..., &underlyingWritten, pOutput);
      if (result != VK_SUCCESS) {
        *pCount = underlyingWritten;
        return result;
      }
    }

    if (underlyingWritten < underlyingCount) {
      *pCount = underlyingWritten;
      return VK_INCOMPLETE;
    }

    const uint32_t remainingCapacity = capacity - underlyingWritten;
    const uint32_t extraWritten = std::min(remainingCapacity, uint32_t(extras.size()));
    for (uint32_t i = 0; i < extraWritten; i++)
      writeExtra(pOutput[underlyingWritten + i], extras[i]);

    *pCount = underlyingWritten + extraWritten;
    return extraWritten == extras.size()
      ? VK_SUCCESS
      : VK_INCOMPLETE;
  }

}
