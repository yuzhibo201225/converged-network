// SPDX-License-Identifier: GPL-3.0-only
// Authored source-derived harness; methods injected from pinned CellReplay.
#include <cstdint>
#include <iostream>
#include <memory>
#include <queue>
#include <vector>
#include <algorithm>
#include "drop_tail_packet_queue.hh"
using namespace std;
class Fixture {
public:
    static constexpr unsigned PACKET_SIZE=1400;
    bool finished_=false, repeat_=false, corrected;
    vector<uint64_t> heavy_pdo_schedule_{100,200,300,400};
    size_t next_delivery_=0;
    uint64_t link_base_timestamp_=0;
    unique_ptr<AbstractPacketQueue> packet_queue_;
    QueuedPacket packet_in_transit_{"",0};
    unsigned packet_in_transit_bytes_left_=0, current_link_queue_size_=0;
    queue<QueuedPacket> output_queue_;
    uint64_t light_output=0;
    Fixture(unsigned limit,bool fix):corrected(fix),packet_queue_(new DropTailPacketQueue("packets="+to_string(limit))){}
    uint64_t next_delivery_time() const;
    void use_a_delivery_opportunity();
    void rationalize(uint64_t now);
    void attempt(uint64_t now,unsigned bytes) {
        rationalize(now);
        unsigned before=packet_queue_->size_packets();
        packet_queue_->enqueue(QueuedPacket(string(bytes,'x'),now));
        if(corrected) current_link_queue_size_+=packet_queue_->size_packets()-before;
        else current_link_queue_size_+=1;
    }
    void write(uint64_t now) {
        while(!output_queue_.empty()) {
            auto packet=output_queue_.front(); output_queue_.pop();
            assert(current_link_queue_size_>0);
            current_link_queue_size_=current_link_queue_size_-1;
            if(packet.contents.size()==150) light_output=now;
        }
    }
};
// INJECT_PINNED_METHODS
int main() {
    cout<<"variant,light_bypass,resident_before_light,counter_before_light,light_release_ms,light_output_ms,excess_ms,final_counter\n";
    for(unsigned v=0;v<3;v++) {
        Fixture f(v==1?2:1,v==2);
        f.attempt(0,1400);f.attempt(0,1400);
        f.rationalize(201);f.write(201);
        unsigned resident=f.packet_queue_->size_packets(),counter=f.current_link_queue_size_;
        DelayQueuePacket next_packet(string(150,'c'),201);
        bool bypass=next_packet.is_bypass_link_queue && f.current_link_queue_size_==0;
        if(bypass) f.light_output=201;else f.attempt(201,150);
        f.rationalize(300);f.write(300);
        f.rationalize(400);f.write(400);
        assert(f.light_output>=201);
        cout<<(v==0?"original_drop":v==1?"original_no_drop":"corrected_drop")<<','<<bypass<<','<<resident<<','<<counter<<",201,"<<f.light_output<<','<<f.light_output-201<<','<<f.current_link_queue_size_<<'\n';
    }
}
