# Architecture

This page describes the internal design of `ThreadPoolXMLRPCServer` using
diagrams rendered from Mermaid source.

---

## Request lifecycle

The sequence from the moment a TCP connection arrives to the moment a response
is sent:

```mermaid
sequenceDiagram
    participant C  as Client
    participant OS as OS TCP stack
    participant AT as Accept thread<br/>(serve_forever)
    participant TP as ThreadPoolExecutor
    participant W  as Worker thread
    participant H  as XML-RPC handler

    C  ->> OS : TCP SYN
    OS ->> AT : accept()
    AT ->> AT : acquire semaphore
    alt capacity available
        AT ->> TP : submit(_process_request_worker)
        AT ->> AT : stats.record_submitted()
        TP ->> W  : schedule on free thread
        W  ->> W  : stats.record_started()
        W  ->> H  : finish_request()
        H  ->> H  : parse XML-RPC body
        H  ->> H  : dispatch to user method
        H  -->> C : HTTP 200 + XML response
        W  ->> W  : stats.record_completed()
        W  ->> AT : semaphore.release()
    else overloaded — CLOSE
        AT ->> C  : close socket (no response)
        AT ->> AT : stats.record_rejected_close()
    else overloaded — FAULT
        AT ->> C  : HTTP 200 + XML-RPC fault body
        AT ->> AT : stats.record_rejected_fault()
    else overloaded — HTTP_503
        AT ->> C  : HTTP 503 Service Unavailable
        AT ->> AT : stats.record_rejected_503()
    else overloaded — BLOCK
        AT ->> AT : semaphore.acquire() — waits
        AT ->> TP : submit (after wait)
    end
```

---

## Threading model

```mermaid
graph TD
    subgraph Main["Main process"]
        direction TB
        AT["Accept thread<br/>socketserver.serve_forever()"]
        SEM["Semaphore<br/>value = max_workers + max_pending"]
        AT -- acquire --> SEM
        SEM -- release --> AT

        subgraph TP["ThreadPoolExecutor (max_workers)"]
            W1["Worker 1"]
            W2["Worker 2"]
            WN["Worker N"]
        end

        AT -- submit --> TP
        TP --> W1
        TP --> W2
        TP --> WN

        ST["_StatsTracker<br/>(mutex-protected)"]
        W1 -- record_started/completed --> ST
        W2 -- record_started/completed --> ST
        WN -- record_started/completed --> ST
        AT -- record_submitted/rejected --> ST
    end

    C1([Client 1]) -- request --> AT
    C2([Client 2]) -- request --> AT
    CN([Client N]) -- request --> AT
    W1 -- response --> C1
    W2 -- response --> C2
    WN -- response --> CN
```

---

## Class hierarchy

```mermaid
classDiagram
    direction LR

    class SimpleXMLRPCServer {
        <<stdlib>>
        +register_function()
        +register_instance()
        +serve_forever()
    }

    class ThreadPoolXMLRPCServer {
        +config: XMLRPCServerConfig
        +stats() ServerStats
        +process_request()
        +submit_request()
        +shutdown_executor()
        -_executor: ThreadPoolExecutor
        -_capacity: Semaphore
        -_stats: _StatsTracker
    }

    class XMLRPCServerConfig {
        <<frozen dataclass>>
        +max_workers: int
        +max_pending: int
        +overload_policy: ServerOverloadPolicy
        +max_request_size: int
        +request_queue_size: int
        +overload_fault_code: int
        +overload_fault_string: str
    }

    class ServerStats {
        <<frozen dataclass>>
        +active: int
        +queued: int
        +rejected_close: int
        +rejected_fault: int
        +rejected_503: int
        +completed: int
        +errored: int
    }

    class ServerOverloadPolicy {
        <<str Enum>>
        BLOCK
        CLOSE
        FAULT
        HTTP_503
    }

    class LimitedXMLRPCRequestHandler {
        +max_request_size: int
        +do_POST()
        +log_error()
    }

    class SimpleXMLRPCRequestHandler {
        <<stdlib>>
        +rpc_paths: tuple
        +do_POST()
    }

    SimpleXMLRPCServer <|-- ThreadPoolXMLRPCServer
    SimpleXMLRPCRequestHandler <|-- LimitedXMLRPCRequestHandler
    ThreadPoolXMLRPCServer *-- XMLRPCServerConfig
    ThreadPoolXMLRPCServer --> ServerStats : stats()
    ThreadPoolXMLRPCServer --> ServerOverloadPolicy
    ThreadPoolXMLRPCServer --> LimitedXMLRPCRequestHandler : uses
```

---

## Request state machine

Each request passes through the following states inside the server:

```mermaid
stateDiagram-v2
    [*] --> Arrived : TCP accept()

    Arrived --> Acquiring : try semaphore

    Acquiring --> Queued     : BLOCK — wait for slot
    Acquiring --> Queued     : slot available
    Acquiring --> Rejected   : no slot + CLOSE/FAULT/HTTP_503

    Queued --> Active        : worker thread picks up request
    Active --> Completed     : finish_request() succeeds
    Active --> Errored       : unhandled exception in worker

    Completed --> [*]
    Errored   --> [*]
    Rejected  --> [*]
```

---

## Capacity model

```mermaid
graph LR
    subgraph Capacity["Total outstanding = max_workers + max_pending"]
        subgraph Pool["ThreadPoolExecutor   (max_workers)"]
            W1[Worker 1]
            W2[Worker 2]
            WN[Worker N]
        end
        subgraph Queue["Pending queue   (max_pending slots)"]
            Q1[Slot 1]
            Q2[Slot 2]
            QM[Slot M]
        end
    end

    R([New request]) --> S{Semaphore}
    S -- slot in pool --> Pool
    S -- pool full, slot in queue --> Queue
    S -- all full + not BLOCK --> X([Reject])
    Queue --> Pool
```

---

## Multi-process scale-out (SO_REUSEPORT)

```mermaid
graph TD
    C([Client traffic]) --> K

    subgraph Kernel["Linux kernel — SO_REUSEPORT load balancer"]
        K[Kernel routes by\nsrc IP+port hash]
    end

    K --> P1
    K --> P2
    K --> PN

    subgraph P1["Worker process 1"]
        S1[ThreadPoolXMLRPCServer\nmax_workers=4]
    end
    subgraph P2["Worker process 2"]
        S2[ThreadPoolXMLRPCServer\nmax_workers=4]
    end
    subgraph PN["Worker process N"]
        SN[ThreadPoolXMLRPCServer\nmax_workers=4]
    end
```

---

## Design decisions

### Why a semaphore instead of a queue?

A `threading.Semaphore` is chosen over a `queue.Queue` because:

1. **Two-level limiting**: The semaphore guards both the worker pool *and* the
   pending queue in one atomic operation — no separate pending-count variable
   needed.
2. **No data movement**: The semaphore slot is acquired before the socket is
   handed to the executor, so the socket never sits in a Python queue consuming
   file-descriptor budget.
3. **BLOCK for free**: When `overload_policy=BLOCK`, `semaphore.acquire()` with
   no timeout blocks the accept thread naturally, backpressuring the OS TCP
   stack at the application layer.

### Why `ThreadPoolExecutor` over `ThreadingMixIn`?

`ThreadingMixIn` spawns one thread per request — unbounded and impossible to
limit. `ThreadPoolExecutor` reuses threads and has a fixed upper bound, giving
predictable memory footprint under load.

### Why inherit from `SimpleXMLRPCServer`?

Constructor-level compatibility with `SimpleXMLRPCServer` means drop-in
replacement: existing code that passes `logRequests`, `allow_none`, etc. works
unchanged. The handler chain and method dispatch are unchanged from the stdlib.
