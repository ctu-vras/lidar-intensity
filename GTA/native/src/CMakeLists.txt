


find_package(Eigen3 REQUIRED)
set(GTAVision_src 
    main.cpp
    export.h
    export.cpp
    main.h
    enums.h
    nativeCaller.h
    natives.h
    types.h
)

add_library(GTAVisionNative SHARED ${GTAVision_src})
target_link_libraries(GTAVisionNative PUBLIC ${PROJECT_SOURCE_DIR}/deps/ScriptHookV.lib ${PROJECT_SOURCE_DIR}/deps/libMinHook.x64.lib)
TARGET_INCLUDE_DIRECTORIES(GTAVisionNative PRIVATE ${EIGEN3_INCLUDE_DIR} ${PROJECT_SOURCE_DIR}/src)
set_target_properties(GTAVisionNative PROPERTIES SUFFIX ".asi" CXX_TARGET 17)

