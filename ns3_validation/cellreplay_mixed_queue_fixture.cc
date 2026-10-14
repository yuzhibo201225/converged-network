// SPDX-License-Identifier: GPL-3.0-only
// Standalone source-derived FIFO harness. Original service methods injected.
#include <cstdint>
#include <iostream>
#include <fstream>
#include <memory>
#include <queue>
#include <vector>
#include <algorithm>
#include "drop_tail_packet_queue.hh"
using namespace std;
struct Record {
    uint64_t id,arrival,release;unsigned size;bool bypass;
    string status="unfinished";int64_t finish=-1;bool actual=false;
};
class Fixture {
public:
    static constexpr unsigned PACKET_SIZE=1400;
    bool finished_=false,repeat_=false,corrected;
    vector<uint64_t> heavy_pdo_schedule_;
    size_t next_delivery_=0;
    uint64_t link_base_timestamp_=0;
    unique_ptr<AbstractPacketQueue> packet_queue_{new DropTailPacketQueue("packets=16")};
    QueuedPacket packet_in_transit_{"",0};
    unsigned packet_in_transit_bytes_left_=0,current_link_queue_size_=0;
    queue<QueuedPacket> output_queue_;
    vector<Record> records;
    explicit Fixture(bool fix):corrected(fix){}
    uint64_t next_delivery_time() const;
    void use_a_delivery_opportunity();
    void rationalize(uint64_t now);
    void attempt(Record& r) {
        unsigned before=packet_queue_->size_packets();
        packet_queue_->enqueue(QueuedPacket(string(r.size,'x'),"",r.arrival,r.release,r.id,r.release));
        if(corrected) current_link_queue_size_+=packet_queue_->size_packets()-before;
        else current_link_queue_size_+=1;
        if(packet_queue_->size_packets()==before) r.status="dropped";
    }
    void write(uint64_t t) {
        while(!output_queue_.empty()) {
            auto p=output_queue_.front();output_queue_.pop();
            auto& r=records.at(p.sequence_number);r.status="completed";r.finish=t;
            assert(current_link_queue_size_>0);
            current_link_queue_size_=current_link_queue_size_-1;
        }
    }
};
// INJECT_PINNED_METHODS
int main(int argc,char**argv) {
    try {
        if(argc!=6)throw runtime_error("heavy planned accounting output end");
        Fixture f(string(argv[3])=="accepted");uint64_t end=stoull(argv[5]);
        ifstream heavy(argv[1]),plans(argv[2]);uint64_t t,n;
        if(!heavy||!plans)throw runtime_error("input open");
        while(heavy>>t>>n)for(uint64_t k=0;k<n;k++)f.heavy_pdo_schedule_.push_back(t);
        if(f.heavy_pdo_schedule_.empty())throw runtime_error("no service");
        Record r;unsigned bypass;
        while(plans>>r.id>>r.arrival>>r.release>>r.size>>bypass){
            r.bypass=bypass;if(r.id!=f.records.size())throw runtime_error("id order");
            f.records.push_back(r);
        }
        size_t position=0;
        while(position<f.records.size()) {
            t=f.records[position].release;if(t>end)break;
            while(f.next_delivery_time()<t){auto st=f.next_delivery_time();f.rationalize(st);f.write(st);}
            f.rationalize(t);
            while(position<f.records.size()&&f.records[position].release==t) {
                auto& p=f.records[position++];
                if(p.bypass&&f.current_link_queue_size_==0){p.status="completed";p.finish=t;p.actual=true;}
                else f.attempt(p);
            }
            f.write(t);
        }
        while(f.next_delivery_time()<=end){auto st=f.next_delivery_time();f.rationalize(st);f.write(st);}
        ofstream out(argv[4]);if(!out)throw runtime_error("output open");
        out<<"packet_id,status,finish_ms,delay_ms,actual_bypass\n";
        for(const auto& p:f.records) {
            out<<p.id<<','<<p.status<<',';
            if(p.finish>=0)out<<p.finish;
            out<<',';if(p.finish>=0)out<<p.finish-p.arrival;
            out<<','<<(p.actual?"True":"False")<<'\n';
        }
        cout<<f.current_link_queue_size_<<' '<<f.packet_queue_->size_packets()+(f.packet_in_transit_bytes_left_?1:0)<<'\n';
        return 0;
    }catch(const exception& e){cerr<<e.what()<<'\n';return 1;}
}
