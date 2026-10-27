---
status: accepted
---

# Share one development GPU with separate training windows

Use a teammate's RTX 5070 machine as a private shared development inference server, with scheduled training windows separate from inference service. This lets teammates work without each loading a GPU model, at the cost of queueing, host availability, and coordination; the GPU variant, VRAM, availability, and access mechanism remain unverified. The development service does not replace the final offline container or establish performance on the organizer's A30.
