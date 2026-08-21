#include "srlinux-c-api.h"

#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <string>

namespace
{

void
Check(bool condition, const std::string& message)
{
    if (!condition)
    {
        std::cerr << "FAIL: " << message << std::endl;
        std::exit(1);
    }
}

struct CallbackState
{
    std::uint64_t calls{0};
    std::uint64_t candidateId{0};
    std::string nextHopGroup;
};

int
Apply(void* userData,
      const char*,
      std::uint32_t,
      std::uint64_t candidateId,
      const char* nextHopGroup)
{
    auto* state = static_cast<CallbackState*>(userData);
    ++state->calls;
    state->candidateId = candidateId;
    state->nextHopGroup = nextHopGroup ? nextHopGroup : "";
    return 1;
}

ir_srlinux_result
Execute(ir_srlinux_adapter_handle* handle,
        const ir_srlinux_candidate* candidates,
        const ir_srlinux_evidence* evidence,
        double nowSeconds)
{
    ir_srlinux_result result{};
    char error[IR_SRLINUX_TEXT_SIZE]{};
    const int ok = ir_srlinux_adapter_execute(handle,
                                               "10.0.4.0/24",
                                               0,
                                               nowSeconds,
                                               "10.0.4.0/24",
                                               1,
                                               candidates,
                                               2,
                                               "10.0.4.0/24",
                                               1,
                                               candidates,
                                               2,
                                               evidence,
                                               2,
                                               1,
                                               &result,
                                               error,
                                               sizeof(error));
    Check(ok == 1, std::string("C API execution failed: ") + error);
    return result;
}

} // namespace

int
main()
{
    const ir_srlinux_candidate candidates[] = {
        {1, 0.0, 1, "ecmp"},
        {2, 0.0, 1, "suppress-s1"},
    };
    ir_srlinux_update_config config{};
    config.suppress_duplicates = 1;
    config.token_rate_per_second = 1.0 / 30.0;
    config.token_burst = 1.0;
    config.min_consecutive_selections = 2;

    CallbackState state;
    char error[IR_SRLINUX_TEXT_SIZE]{};
    ir_srlinux_adapter_handle* handle =
        ir_srlinux_adapter_create("ir-deg", &config, Apply, &state, error, sizeof(error));
    Check(handle != nullptr, std::string("C API creation failed: ") + error);

    Check(ir_srlinux_adapter_seed_active(handle,
                                         "10.0.4.0/24",
                                         1,
                                         candidates,
                                         2,
                                         0,
                                         1,
                                         0.0,
                                         error,
                                         sizeof(error)) == 1,
          std::string("active-view seed failed: ") + error);

    ir_srlinux_evidence healthy[] = {
        {1, "queue", 0.0, 1.0, 0.1, 30.0, "application"},
        {2, "queue", 1.0, 1.0, 0.1, 30.0, "application"},
    };
    const auto duplicate = Execute(handle, candidates, healthy, 0.1);
    Check(duplicate.candidate_id == 1, "healthy evidence should preserve ECMP");
    Check(duplicate.action_status == IR_SRLINUX_ACTION_SUPPRESSED_DUPLICATE,
          "seeded ECMP should be a duplicate");
    Check(state.calls == 0, "duplicate must not invoke the device callback");

    ir_srlinux_evidence degraded[] = {
        {1, "queue", 2.0, 1.0, 0.2, 30.0, "application"},
        {2, "queue", 0.0, 1.0, 0.2, 30.0, "application"},
    };
    const auto qualifying = Execute(handle, candidates, degraded, 0.2);
    Check(qualifying.candidate_id == 2, "degraded evidence should select suppression");
    Check(qualifying.action_status == IR_SRLINUX_ACTION_SUPPRESSED_DWELL,
          "first selection should await qualification");
    Check(state.calls == 0, "unqualified selection must not invoke the callback");

    degraded[0].timestamp_seconds = 0.3;
    degraded[1].timestamp_seconds = 0.3;
    const auto applied = Execute(handle, candidates, degraded, 0.3);
    Check(applied.action_status == IR_SRLINUX_ACTION_ADMITTED && applied.backend_applied == 1,
          "second selection should apply suppression");
    Check(state.calls == 1 && state.candidateId == 2,
          "callback should receive the selected candidate exactly once");
    Check(state.nextHopGroup == "suppress-s1",
          "callback should receive the native next-hop-group mapping");

    const auto suppressedDuplicate = Execute(handle, candidates, degraded, 0.4);
    Check(suppressedDuplicate.action_status == IR_SRLINUX_ACTION_SUPPRESSED_DUPLICATE,
          "installed suppression should be a duplicate");

    healthy[0].timestamp_seconds = 0.5;
    healthy[1].timestamp_seconds = 0.5;
    Check(Execute(handle, candidates, healthy, 0.5).action_status ==
              IR_SRLINUX_ACTION_SUPPRESSED_DWELL,
          "first restore selection should await qualification");
    healthy[0].timestamp_seconds = 0.6;
    healthy[1].timestamp_seconds = 0.6;
    Check(Execute(handle, candidates, healthy, 0.6).action_status ==
              IR_SRLINUX_ACTION_SUPPRESSED_BUDGET,
          "qualified restore should respect the shared action budget");
    Check(state.calls == 1, "budget suppression must not invoke the callback");

    ir_srlinux_adapter_destroy(handle);
    std::cout << "PASS: SR Linux C API" << std::endl;
    return 0;
}
