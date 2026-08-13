/** Add-on log level enum — mirrors config.yaml `log_level` schema. */
export type LogLevel =
  | 'trace'
  | 'debug'
  | 'info'
  | 'notice'
  | 'warning'
  | 'error'
  | 'fatal'

/**
 * A single ingress route used by RouteEditor (UI shape;
 * maps to the `additional_hosts` Supervisor option).
 */
export interface Route {
  hostname: string
  service: string
  disableChunkedEncoding: boolean
}

/** `additional_hosts` entry exactly as stored in the Supervisor options. */
export interface AdditionalHost {
  hostname: string
  service: string
  disableChunkedEncoding?: boolean | null
}

/** Response of GET /api/options (token masked). */
export interface OptionsRead {
  external_hostname: string
  additional_hosts: AdditionalHost[]
  tunnel_name: string | null
  catch_all_service: string | null
  nginx_proxy_manager: boolean | null
  post_quantum: boolean | null
  run_parameters: string[] | null
  log_level: LogLevel | null
  tunnel_token_set: boolean
  tunnel_token_masked: string
}

/**
 * Request body for PUT /api/options.
 * tunnel_token semantics: undefined/null = keep, '' = remove, value = replace.
 */
export interface OptionsWrite {
  external_hostname: string
  additional_hosts: AdditionalHost[]
  tunnel_name?: string | null
  catch_all_service?: string | null
  nginx_proxy_manager?: boolean | null
  tunnel_token?: string | null
  post_quantum?: boolean | null
  run_parameters?: string[] | null
  log_level?: LogLevel | null
}

/** Tunnel status derived from the cloudflared metrics /ready endpoint. */
export interface TunnelStatus {
  status: 'running' | 'starting' | 'stopped'
  ready_connections: number
  metrics_reachable: boolean
}

/** Response of GET /api/health. */
export interface HealthStatus {
  status: string
  supervisor_connected: boolean
  addon_version: string | null
  addon_state: string | null
  tunnel: TunnelStatus
  restart_error: string | null
}

export type SetupMode = 'local' | 'token'

/** Response of GET /api/wizard/state. */
export interface WizardState {
  mode: SetupMode
  has_cert: boolean
  has_tunnel: boolean
  tunnel_uuid: string | null
  login_url: string | null
  tunnel_status: string
  unconfigured: boolean
  prepare_failed: boolean
}
