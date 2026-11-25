import { io } from 'socket.io-client'

let socket = null

// Frappe's realtime server uses one namespace per site. Behind nginx it shares the page's host;
// on a development bench (page served on a port) it listens on `socketio_port`.
export function getSocket() {
  if (socket) return socket
  const { protocol, hostname, port } = window.location
  const site = window.site_name || hostname
  const host = port && window.socketio_port ? `${hostname}:${window.socketio_port}` : window.location.host
  socket = io(`${protocol}//${host}/${site}`, { withCredentials: true, reconnectionAttempts: 3 })
  return socket
}
