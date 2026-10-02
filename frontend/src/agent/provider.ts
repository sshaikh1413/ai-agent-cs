/**
 * The only module the Bookly chat UI talks to.
 *
 * Screens import `getAgentProvider()` from here. They do not call `fetch`
 * themselves, and they do not know whether the desk is the demo agent or a
 * live model with real order and returns APIs.
 *
 * Leave `VITE_AGENT_BASE_URL` unset in development so requests go to `/api`
 * on this Vite server, which proxies to the FastAPI desk. Set it when the
 * API lives on another origin. To swap implementations, replace
 * `createHttpAgentProvider` or point the base URL at a service that speaks
 * this same JSON contract.
 */

export type AgentRole = "user" | "assistant"

export interface AgentTurn {
  role: AgentRole
  content: string
}

export type AgentIntent =
  | "order_status"
  | "return_refund"
  | "shipping"
  | "password_reset"
  | "policy"
  | "clarify"
  | "out_of_scope"

export type CustomerId = "cust_becky" | "cust_bob"

export interface AgentRequest {
  message: string
  history: AgentTurn[]
  conversation_id?: string
  customer_id?: CustomerId
}

export type ToolName =
  | "list_recent_orders"
  | "get_order"
  | "get_refund_options"
  | "start_return"
  | "recommend_book"
  | "issue_goodwill_discount"

export interface ToolTrace {
  name: ToolName
  summary: string
}

export interface AgentReply {
  reply: string
  intent: AgentIntent
  tools: ToolTrace[]
  conversation_id?: string
}

export interface DeskOrder {
  id: string
  customer_name: string
  email: string
  summary: string
}

export interface DeskInfo {
  agent_name: string
  can_help: string[]
  sample_orders: DeskOrder[]
  prompts: string[]
  customer_id: CustomerId
  customer_name: string
}

export interface AgentProvider {
  reply(request: AgentRequest, signal?: AbortSignal): Promise<AgentReply>
  desk(customerId?: CustomerId, signal?: AbortSignal): Promise<DeskInfo>
}

export class AgentDeskError extends Error {
  constructor(message: string) {
    super(message)
    this.name = "AgentDeskError"
  }
}

const TOOLS = new Set<ToolName>([
  "list_recent_orders",
  "get_order",
  "get_refund_options",
  "start_return",
  "recommend_book",
  "issue_goodwill_discount",
])

const INTENTS = new Set<AgentIntent>([
  "order_status",
  "return_refund",
  "shipping",
  "password_reset",
  "policy",
  "clarify",
  "out_of_scope",
])

function apiBase(): string {
  const configured = import.meta.env.VITE_AGENT_BASE_URL
  if (typeof configured === "string" && configured.trim()) {
    return configured.trim().replace(/\/$/, "")
  }
  return ""
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json()
  } catch {
    throw new AgentDeskError(
      "Mara's desk sent a reply this page couldn't read. Nothing was filed.",
    )
  }
}

function assertReply(value: unknown): AgentReply {
  if (typeof value !== "object" || value === null) {
    throw new AgentDeskError(
      "Mara's desk sent an unexpected reply. Nothing was filed.",
    )
  }
  const record = value as Record<string, unknown>
  if (typeof record.reply !== "string" || !record.reply.trim()) {
    throw new AgentDeskError(
      "Mara's desk sent an unexpected reply. Nothing was filed.",
    )
  }
  if (typeof record.intent !== "string" || !INTENTS.has(record.intent as AgentIntent)) {
    throw new AgentDeskError(
      "Mara's desk sent an unexpected reply. Nothing was filed.",
    )
  }
  const conversation_id =
    typeof record.conversation_id === "string" && record.conversation_id.trim()
      ? record.conversation_id
      : undefined
  return {
    reply: record.reply,
    intent: record.intent as AgentIntent,
    tools: assertTools(record.tools),
    conversation_id,
  }
}

function assertTools(value: unknown): ToolTrace[] {
  if (value === undefined || value === null) return []
  if (!Array.isArray(value)) {
    throw new AgentDeskError(
      "Mara's desk sent an unexpected reply. Nothing was filed.",
    )
  }
  return value.map((item) => {
    if (typeof item !== "object" || item === null) {
      throw new AgentDeskError(
        "Mara's desk sent an unexpected reply. Nothing was filed.",
      )
    }
    const tool = item as Record<string, unknown>
    if (typeof tool.name !== "string" || !TOOLS.has(tool.name as ToolName)) {
      throw new AgentDeskError(
        "Mara's desk sent an unexpected reply. Nothing was filed.",
      )
    }
    if (typeof tool.summary !== "string") {
      throw new AgentDeskError(
        "Mara's desk sent an unexpected reply. Nothing was filed.",
      )
    }
    return { name: tool.name as ToolName, summary: tool.summary }
  })
}

function assertDesk(value: unknown): DeskInfo {
  if (typeof value !== "object" || value === null) {
    throw new AgentDeskError("The order list came back in an unexpected shape.")
  }
  const record = value as Record<string, unknown>
  if (typeof record.agent_name !== "string" || !Array.isArray(record.sample_orders)) {
    throw new AgentDeskError("The order list came back in an unexpected shape.")
  }
  if (!Array.isArray(record.can_help) || !Array.isArray(record.prompts)) {
    throw new AgentDeskError("The order list came back in an unexpected shape.")
  }
  const sample_orders: DeskOrder[] = []
  for (const item of record.sample_orders) {
    if (typeof item !== "object" || item === null) {
      throw new AgentDeskError("The order list came back in an unexpected shape.")
    }
    const order = item as Record<string, unknown>
    if (
      typeof order.id !== "string" ||
      typeof order.customer_name !== "string" ||
      typeof order.email !== "string" ||
      typeof order.summary !== "string"
    ) {
      throw new AgentDeskError("The order list came back in an unexpected shape.")
    }
    sample_orders.push({
      id: order.id,
      customer_name: order.customer_name,
      email: order.email,
      summary: order.summary,
    })
  }
  if (record.customer_id !== "cust_becky" && record.customer_id !== "cust_bob") {
    throw new AgentDeskError("The order list came back in an unexpected shape.")
  }
  if (typeof record.customer_name !== "string" || !record.customer_name.trim()) {
    throw new AgentDeskError("The order list came back in an unexpected shape.")
  }
  return {
    agent_name: record.agent_name,
    can_help: record.can_help.filter((item): item is string => typeof item === "string"),
    sample_orders,
    prompts: record.prompts.filter((item): item is string => typeof item === "string"),
    customer_id: record.customer_id,
    customer_name: record.customer_name,
  }
}

export function createHttpAgentProvider(baseUrl = apiBase()): AgentProvider {
  return {
    async reply(request, signal) {
      let response: Response
      try {
        response = await fetch(`${baseUrl}/api/chat`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(request),
          signal,
        })
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") {
          throw error
        }
        throw new AgentDeskError(
          "Mara's desk didn't answer. Nothing was filed. Try again in a moment.",
        )
      }
      if (!response.ok) {
        throw new AgentDeskError(
          "Mara's desk didn't answer. Nothing was filed. Try again in a moment.",
        )
      }
      return assertReply(await readJson(response))
    },
    async desk(customerId = "cust_becky", signal) {
      const query = new URLSearchParams({ customer_id: customerId })
      let response: Response
      try {
        response = await fetch(`${baseUrl}/api/desk?${query}`, { signal })
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") {
          throw error
        }
        throw new AgentDeskError("The order list didn't load.")
      }
      if (!response.ok) {
        throw new AgentDeskError("The order list didn't load.")
      }
      return assertDesk(await readJson(response))
    },
  }
}

export function getAgentProvider(): AgentProvider {
  return createHttpAgentProvider()
}
