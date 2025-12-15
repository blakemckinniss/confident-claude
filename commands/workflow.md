# Workflow: Multi-Session Step-Based Operations

Manage complex multi-step workflows that can be paused and resumed across sessions.
Inspired by BMAD-METHOD's step-file architecture for continuable operations.

## Arguments
- `$ARGUMENTS` - Command: create|resume|status|list|complete

## Usage Examples
- `/workflow create migration 5` - Create 5-step migration workflow
- `/workflow resume migration` - Resume existing workflow
- `/workflow status` - Show current workflow progress
- `/workflow list` - List all workflows
- `/workflow complete 3` - Mark step 3 complete

---

## Workflow Management Commands

**Based on the arguments, execute the appropriate workflow operation:**

### If "create <name> <steps>" or "create <name>":
```python
from lib._step_workflow import StepWorkflow

# Parse: workflow create <name> [steps]
workflow = StepWorkflow.create(
    name="<name>",
    total_steps=<steps or 3>,
    goal="<infer from context or ask>"
)
workflow.save()
print(f"Created workflow: {workflow.state.workflow_id}")
print(workflow.get_progress_summary())
```

### If "resume <name>":
```python
from lib._step_workflow import StepWorkflow

workflow = StepWorkflow.load("<name>")
if workflow:
    next_step = workflow.get_resume_point()
    print(f"Resuming from step {next_step}")
    print(workflow.get_progress_summary())
else:
    print("No workflow found with that name")
```

### If "status":
```python
from lib._step_workflow import list_workflows

workflows = list_workflows()
for wf in workflows[:5]:
    print(f"• {wf['name']} ({wf['progress']}) - {wf['goal']}")
```

### If "list":
```python
from lib._step_workflow import list_workflows

workflows = list_workflows()
print(f"Found {len(workflows)} workflows:")
for wf in workflows:
    print(f"  {wf['id']}: {wf['name']} ({wf['progress']})")
```

### If "complete <step>":
```python
# Mark step as complete in current workflow
# Store findings if provided
workflow.complete_step(<step>, findings={"summary": "<brief>"})
workflow.save()
```

---

## Step Workflow Pattern

When working on a complex multi-step task:

1. **Create workflow**: `workflow = StepWorkflow.create("task-name", total_steps=5)`
2. **Define steps**: `workflow.define_step(1, "Analyze current state")`
3. **Start step**: `workflow.start_step(1)`
4. **Do work**: Execute the step's task
5. **Complete step**: `workflow.complete_step(1, findings={"key": "value"})`
6. **Save progress**: `workflow.save()` (persists to disk)

### Resuming After Session Break

```python
workflow = StepWorkflow.load("task-name")
if workflow:
    next_step = workflow.get_resume_point()  # Returns first incomplete step
    print(workflow.get_progress_summary())
    workflow.start_step(next_step)
```

### Branching for Alternative Paths

```python
workflow.create_branch("approach-a", from_step=3)
workflow.switch_branch("approach-a")
# Work on alternative approach...
```

---

## Integration with Beads

For tasks tracked with beads, workflows provide step-level granularity:

```python
# Bead tracks the overall task
# Workflow tracks individual steps within that task

workflow = StepWorkflow.create("bead-xyz-impl", total_steps=4, goal="Implement feature XYZ")
workflow.add_context("bead_id", "bead-xyz")
workflow.save()
```
