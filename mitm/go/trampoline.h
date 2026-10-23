#ifndef TRAMPOLINE_H
#define TRAMPOLINE_H

#include <stdint.h>

typedef void (*frame_cb)(const uint8_t *data, int len);
typedef void (*tcp_accept_cb)(uint64_t conn_id, const char *dst_ip, int dst_port);
typedef void (*tcp_data_cb)(uint64_t conn_id, const uint8_t *data, int len);
typedef void (*tcp_close_cb)(uint64_t conn_id);
typedef void (*udp_packet_cb)(const char *src_ip, int src_port, const char *dst_ip, int dst_port, const uint8_t *data, int len);

void frame_cb_call(frame_cb f, const uint8_t *data, int len);
void tcp_accept_cb_call(tcp_accept_cb f, uint64_t id, const char *ip, int port);
void tcp_data_cb_call(tcp_data_cb f, uint64_t id, const uint8_t *data, int len);
void tcp_close_cb_call(tcp_close_cb f, uint64_t id);
void udp_packet_cb_call(udp_packet_cb f, const char *sip, int sport, const char *dip, int dport, const uint8_t *data, int len);

#endif
