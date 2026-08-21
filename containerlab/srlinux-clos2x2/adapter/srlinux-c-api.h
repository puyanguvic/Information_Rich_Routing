#ifndef IR_SRLINUX_C_API_H
#define IR_SRLINUX_C_API_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C"
{
#endif

#define IR_SRLINUX_NAME_SIZE 64
#define IR_SRLINUX_TEXT_SIZE 256

typedef struct ir_srlinux_adapter_handle ir_srlinux_adapter_handle;

typedef enum
{
    IR_SRLINUX_DECISION_UNKNOWN = 0,
    IR_SRLINUX_DECISION_SELECTED = 1,
    IR_SRLINUX_DECISION_FALLBACK = 2,
    IR_SRLINUX_DECISION_NO_CANDIDATE = 3,
} ir_srlinux_decision_status;

typedef enum
{
    IR_SRLINUX_ACTION_NO_ACTION = 0,
    IR_SRLINUX_ACTION_ADMITTED = 1,
    IR_SRLINUX_ACTION_SUPPRESSED_DUPLICATE = 2,
    IR_SRLINUX_ACTION_SUPPRESSED_DWELL = 3,
    IR_SRLINUX_ACTION_SUPPRESSED_BUDGET = 4,
} ir_srlinux_action_status;

typedef struct
{
    uint64_t id;
    double stable_cost;
    int eligible;
    const char* next_hop_group;
} ir_srlinux_candidate;

typedef struct
{
    uint64_t candidate_id;
    const char* kind;
    double value;
    double confidence;
    double timestamp_seconds;
    double expires_after_seconds;
    const char* source;
} ir_srlinux_evidence;

typedef struct
{
    int suppress_duplicates;
    double dwell_seconds;
    double token_rate_per_second;
    double token_burst;
    uint32_t min_consecutive_selections;
} ir_srlinux_update_config;

/** Return 1 for applied, 0 for rejected, and -1 for a transport failure. */
typedef int (*ir_srlinux_apply_callback)(void* user_data,
                                         const char* destination,
                                         uint32_t traffic_class,
                                         uint64_t candidate_id,
                                         const char* next_hop_group);

typedef struct
{
    int decision_status;
    int has_selection;
    uint64_t candidate_id;
    double score;
    int action_status;
    uint64_t action_generation;
    int backend_attempted;
    int backend_applied;
    char policy[IR_SRLINUX_NAME_SIZE];
    char decision_reason[IR_SRLINUX_TEXT_SIZE];
    char action_reason[IR_SRLINUX_TEXT_SIZE];
    char backend_detail[IR_SRLINUX_TEXT_SIZE];
    char next_hop_group[IR_SRLINUX_NAME_SIZE];
} ir_srlinux_result;

ir_srlinux_adapter_handle* ir_srlinux_adapter_create(
    const char* program,
    const ir_srlinux_update_config* update_config,
    ir_srlinux_apply_callback callback,
    void* user_data,
    char* error,
    size_t error_size);

void ir_srlinux_adapter_destroy(ir_srlinux_adapter_handle* handle);

int ir_srlinux_adapter_seed_active(ir_srlinux_adapter_handle* handle,
                                   const char* scope,
                                   uint64_t generation,
                                   const ir_srlinux_candidate* candidates,
                                   size_t candidate_count,
                                   uint32_t traffic_class,
                                   uint64_t candidate_id,
                                   double now_seconds,
                                   char* error,
                                   size_t error_size);

int ir_srlinux_adapter_execute(ir_srlinux_adapter_handle* handle,
                               const char* destination,
                               uint32_t traffic_class,
                               double now_seconds,
                               const char* selection_scope,
                               uint64_t selection_generation,
                               const ir_srlinux_candidate* selection_candidates,
                               size_t selection_candidate_count,
                               const char* authority_scope,
                               uint64_t authority_generation,
                               const ir_srlinux_candidate* authority_candidates,
                               size_t authority_candidate_count,
                               const ir_srlinux_evidence* evidence,
                               size_t evidence_count,
                               int apply_action,
                               ir_srlinux_result* result,
                               char* error,
                               size_t error_size);

void ir_srlinux_adapter_reset(ir_srlinux_adapter_handle* handle);

#ifdef __cplusplus
}
#endif

#endif // IR_SRLINUX_C_API_H
