build_lib_example(
    NAME information-routing-example
    SOURCE_FILES information-routing-example.cc
    LIBRARIES_TO_LINK ${libinformation-routing}
)

build_lib_example(
    NAME information-routing-wan-experiment
    SOURCE_FILES information-routing-wan-experiment.cc
    LIBRARIES_TO_LINK ${libinformation-routing}
                      ${libapplications}
                      ${libflow-monitor}
)
