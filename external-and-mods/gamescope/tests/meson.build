catch2_dep = dependency('catch2-with-main', required: true, fallback: ['catch2', 'catch2_with_main_dep'])

srcdir = '../src'
unittest_src = []
foreach src : gamescope_core_src + ['Script/Script.cpp', 'convar_script.cpp', 'edid.cpp']
	unittest_src += srcdir / src
endforeach

gamescope_tests = executable(
	'gamescope_tests',
	unittest_src + ['test_convar.cpp', 'test_focus_placement.cpp', 'test_mangoapp_config.cpp', 'test_mangoapp_control.cpp', 'test_mode_list.cpp', 'test_process.cpp', 'test_upscale.cpp', 'test_utils_parsers.cpp', 'test_utils_string.cpp', 'test_vrclient_detect.cpp', 'test_display_lookup.cpp', 'test_drm_composition.cpp', 'test_client_format_policy.cpp', 'test_edid.cpp'],
	include_directories: [srcdir, sol2_include],
	dependencies: [catch2_dep, luajit_dep, cap_dep, displayinfo_dep, drm_dep, glm_dep, wlroots_dep],
	cpp_args: gamescope_cpp_args,
)

reaper_test_helper = executable('reaper_test_helper', 'reaper_test_helper.cpp')

test('convar', gamescope_tests, args: ['[convar]'])
test('focus_placement', gamescope_tests, args: ['[focus_placement]'])
test('mangoapp_config', gamescope_tests, args: ['[mangoapp_config]'])
test('mangoapp_control', gamescope_tests, args: ['[mangoapp_control]'])
test('mode_list', gamescope_tests, args: ['[mode_list]'])
test('upscale', gamescope_tests, args: ['[upscale]'])
test('utils/parsers', gamescope_tests, args: ['[parsers]'])
test('utils/process', gamescope_tests, args: ['[process]'], depends: [reaper_test_helper])
test('utils/string', gamescope_tests, args: ['[string]'])
test('vrclient_detect', gamescope_tests, args: ['[vrclient_detect]'])

test_wsi_hdr_surface_formats = executable(
	'test_wsi_hdr_surface_formats',
	['test_wsi_hdr_surface_formats.cpp'],
	include_directories: ['../layer'],
	dependencies: [catch2_dep, vulkan_dep],
)
test('wsi-hdr-surface-formats', test_wsi_hdr_surface_formats)

test('edid', gamescope_tests, args: ['[edid]'])
test('display', gamescope_tests, args: ['[display]'])
test('hdr', gamescope_tests, args: ['[hdr]'])
test('dmabuf', gamescope_tests, args: ['[dmabuf]'])
