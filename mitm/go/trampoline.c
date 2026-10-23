#include "trampoline.h"

void frame_cb_call(frame_cb f, const uint8_t *data, int len) {
    f(data, len);
}

void tcp_accept_cb_call(tcp_accept_cb f, uint64_t id, const char *ip, int port) {
    f(id, ip, port);
}

void tcp_data_cb_call(tcp_data_cb f, uint64_t id, const uint8_t *data, int len) {
    f(id, data, len);
}

void tcp_close_cb_call(tcp_close_cb f, uint64_t id) {
    f(id);
}

void udp_packet_cb_call(udp_packet_cb f, const char *sip, int sport, const char *dip, int dport, const uint8_t *data, int len) {
    f(sip, sport, dip, dport, data, len);
}
