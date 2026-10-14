// SPDX-License-Identifier: GPL-3.0-only
// Source-derived coupling harness; queue implementation is compiled unchanged.
// CellularQueue snippets attributed to williamsentosa95/cellreplay, pinned V24.
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <utility>
#include "drop_tail_packet_queue.hh"

struct Fixture {
    DropTailPacketQueue queue;
    unsigned current_link_queue_size_ = 0;
    unsigned attempts = 0, accepted = 0, dropped = 0, outputs = 0;
    bool corrected;
    Fixture(unsigned limit, bool fix): queue("packets=" + std::to_string(limit)), corrected(fix) {}
    void enqueue(unsigned bytes) {
        unsigned before = queue.size_packets();
        queue.enqueue(QueuedPacket(std::string(bytes, 'x'), 0));
        // Original upstream increment, or explicitly separate derivative.
        if (corrected) current_link_queue_size_ += queue.size_packets() - before;
        else current_link_queue_size_ += 1;
        attempts++;
        if (queue.size_packets() > before) accepted++; else dropped++;
    }
    void drain() {
        while (!queue.empty()) {
            auto packet = queue.dequeue();
            (void)packet;
            assert(current_link_queue_size_ > 0);
            current_link_queue_size_ = current_link_queue_size_ - 1;
            outputs++;
        }
    }
    bool probe() {
        DelayQueuePacket next_packet(std::string(150, 'c'), 0);
        return next_packet.is_bypass_link_queue && current_link_queue_size_ == 0;
    }
    void record(const char* variant, const char* event) {
        std::cout << variant << ',' << event << ',' << queue.size_packets() << ','
                  << current_link_queue_size_ << ',' << attempts << ',' << accepted
                  << ',' << dropped << ',' << outputs << ',' << probe() << '\n';
    }
};
int main() {
    std::cout << "variant,event,resident,counter,attempts,accepted,dropped,outputs,light_bypass\n";
    for (unsigned v=0; v<3; ++v) {
        const char* name = v==0 ? "original_drop" : v==1 ? "original_no_drop" : "corrected_drop";
        Fixture f(v==1 ? 2 : 1, v==2);
        f.record(name,"initial");
        f.enqueue(1400); f.record(name,"first_attempt");
        f.enqueue(1400); f.record(name,"second_attempt");
        f.drain(); f.record(name,"drained");
        bool bypass=f.probe();
        if (!bypass) f.enqueue(150);
        f.record(name,"light_probe");
        f.drain(); f.record(name,"final");
    }
}
