// SPDX-License-Identifier: GPL-3.0-only
// Differential fixture: selected original CellReplay methods, not a full emulator.
// Upstream: williamsentosa95/cellreplay, commit2ca662cb01a222dd7fcc10f9ed79293803b4ef21.
// Original GPL notices retained in the source acquisition directory.
#include <algorithm>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>
using namespace std;
class CellularQueue {
public:
    static const unsigned int PACKET_SIZE=1400;
    struct DelayPDOInstance {
        uint64_t time; int delay; vector<int> pdo;
        DelayPDOInstance(uint64_t t,int d,vector<int> p):time(t),delay(d),pdo(p){}
    };
    vector<DelayPDOInstance> delay_pdo_traces_;
    vector<double> psize_latency_offset_;
    uint64_t delay_base_timestamp_=0,pdo_base_timestamp_=0,last_delay_queue_release_time_=0,end_release_time_=0;
    unsigned int current_delay_pdo_idx_=0,current_pdo_size_=1,current_pdo_idx_=0;
    int current_base_delay_=-1,curr_delivery_opportunity_=1400,long_to_short_timer_=0;
    bool bypass_link_pdo_=true;
    uint64_t get_pkt_release_time_from_trace(const uint64_t &,const vector<DelayPDOInstance> &,const unsigned int &);
    uint64_t get_pkt_release_time(const uint64_t &,const string &);
    double get_psize_latency_offset(const unsigned int &);
    void emit(uint64_t now,unsigned int size,uint64_t id,uint64_t cohort,ofstream &out);
};
uint64_t CellularQueue::get_pkt_release_time_from_trace(const uint64_t & time, const vector<DelayPDOInstance> & delay_pdo_trace, const unsigned int & packet_size) {
    int64_t relative_timestamp_ms = (time - delay_base_timestamp_);
    uint64_t delay_ms = 0;
    uint64_t release_time = time;
    int64_t time_gap_from_base_pdo = relative_timestamp_ms - pdo_base_timestamp_;

    int branch = -1;
    
    // Start a new short pdo trace when the queue is empty for long_to_short_timer_
    // Or when the system start (current_base_delay_  < 0)
    bool start_new_short_pdo_trace = (current_base_delay_ < 0) || (time + current_base_delay_ > last_delay_queue_release_time_ + long_to_short_timer_);

    if (start_new_short_pdo_trace) {

        // Search for the correct instance
        while ( delay_pdo_trace[current_delay_pdo_idx_ + 1].time <= relative_timestamp_ms ) {
            current_delay_pdo_idx_ += 1;
            // Repeat the trace if we already exceed the trace length
            if (current_delay_pdo_idx_ >= (delay_pdo_trace.size() - 1)) {
                // Reset the trace
                delay_base_timestamp_ = delay_base_timestamp_ + delay_pdo_trace[current_delay_pdo_idx_].time;
                relative_timestamp_ms = time - delay_base_timestamp_;
                current_delay_pdo_idx_ = 0;
            }
            
        }

        current_pdo_size_ = delay_pdo_trace[current_delay_pdo_idx_].pdo.size();
        
        // Interpolate the base delay through linear regression
        float ratio = (relative_timestamp_ms - delay_pdo_trace[current_delay_pdo_idx_].time) / float(delay_pdo_trace[current_delay_pdo_idx_ + 1].time - delay_pdo_trace[current_delay_pdo_idx_].time);
        float adjusted_delay = ratio * float(delay_pdo_trace[current_delay_pdo_idx_ + 1].delay - delay_pdo_trace[current_delay_pdo_idx_].delay);
        
        // This is the base delay for the packet within this PDO instance
        delay_ms = int(delay_pdo_trace[current_delay_pdo_idx_].delay + adjusted_delay);
        current_base_delay_ = delay_ms;

        release_time = time + delay_ms;
        bypass_link_pdo_ = true;
        pdo_base_timestamp_ = relative_timestamp_ms;
        current_pdo_idx_ = 0;
        curr_delivery_opportunity_ = PACKET_SIZE - packet_size;
        branch = 1;
    } else {
        // Use the current Short PDO
        int64_t timestamp_from_pdo_base = relative_timestamp_ms - pdo_base_timestamp_;

        // Find the correct PDO time
        while (current_pdo_idx_ < current_pdo_size_ && timestamp_from_pdo_base > delay_pdo_trace[current_delay_pdo_idx_].pdo[current_pdo_idx_]) {
            current_pdo_idx_ += 1;
            curr_delivery_opportunity_ = PACKET_SIZE;
        }    

        if (curr_delivery_opportunity_ < packet_size) {
            current_pdo_idx_ += 1;
            curr_delivery_opportunity_ = PACKET_SIZE;
        }

        // Burn a delivery opportunity
        curr_delivery_opportunity_ = curr_delivery_opportunity_ - packet_size;
        
        if (current_pdo_idx_ >= current_pdo_size_) { // This packet uses to light PDO
            bypass_link_pdo_ = false;
            release_time = max(time + current_base_delay_,  time + delay_pdo_trace[current_delay_pdo_idx_].pdo[current_pdo_size_ - 1]);
            branch = 2;
        } else { // This packet already exceed the light PDO and it should use heavy PDO
            assert(delay_pdo_trace[current_delay_pdo_idx_].pdo[current_pdo_idx_] >= timestamp_from_pdo_base);
            release_time = time + current_base_delay_ + (delay_pdo_trace[current_delay_pdo_idx_].pdo[current_pdo_idx_] - timestamp_from_pdo_base);
            bypass_link_pdo_ = true; 
            branch = 3;
        }
    }   
    last_delay_queue_release_time_ = release_time; 
    return release_time;
}

uint64_t CellularQueue::get_pkt_release_time(const uint64_t & time, const string & contents) {
    uint64_t release_time = get_pkt_release_time_from_trace(time, delay_pdo_traces_, contents.size());
    return release_time;
}


double CellularQueue::get_psize_latency_offset(const unsigned int & psize) {
    double result = 0;

    if (psize_latency_offset_.size() == 0) {
        result = 0;
    } else {
        int idx = (psize / 100) - 1;
        int remainder = psize % 100;
        if (idx < 0) { // For psize < 100, the offset will be based on 100 bytes
            result = psize_latency_offset_[0];
        } else if (idx >= psize_latency_offset_.size() - 1) {
            result = psize_latency_offset_.back();
        } else {
            result = psize_latency_offset_[idx] + ((remainder / 100.0) * (psize_latency_offset_[idx + 1] - psize_latency_offset_[idx]));
        }
    }
    return result;
}


void CellularQueue::emit(uint64_t now,unsigned int size,uint64_t id,uint64_t cohort,ofstream &out) {
    if(size==0||size>1400||now>=delay_pdo_traces_.back().time)throw runtime_error("fixture domain");
    string contents(size,'x');
    const bool reset=(current_base_delay_<0)||(now+current_base_delay_>last_delay_queue_release_time_+long_to_short_timer_);
    uint64_t release_time = get_pkt_release_time(now, contents);

    const uint64_t raw_release = release_time;
    // Apply latency offset adjustment based on psize, but apply this only if it does not cause out-of-order
    int latency_offset = int(round(get_psize_latency_offset(contents.size())));
    if (release_time + latency_offset >= end_release_time_) {
        release_time = release_time + latency_offset;
    }

    const bool clamped = release_time < end_release_time_;
    if (release_time < end_release_time_) {
        release_time = end_release_time_;
        bypass_link_pdo_ = false;
    }

    assert(release_time >= end_release_time_);
    end_release_time_ = release_time;
    uint64_t delay_ms = release_time - now;


    out<<id<<","<<cohort<<","<<now<<","<<size<<","<<raw_release<<","<<release_time<<","<<delay_ms<<","<<current_base_delay_<<","
       <<(reset?"True":"False")<<","<<(bypass_link_pdo_?"True":"False")<<","<<(clamped?"True":"False")<<"\n";
}
int main(int argc,char **argv) {
    try {
        if(argc!=6&&argc!=7)throw runtime_error("light offset size timer output [events]");
        CellularQueue q; q.long_to_short_timer_=stoi(argv[4]);
        ifstream light(argv[1]),offsets(argv[2]);string line;
        if(!light||!offsets)throw runtime_error("fixture input");
        while(getline(light,line)){
            istringstream h(line);uint64_t t;int d,v;vector<int> p;
            if(!(h>>t>>d))throw runtime_error("light parse");
            while(h>>v)p.push_back(v);
            if(p.empty()||(!q.delay_pdo_traces_.empty()&&t<=q.delay_pdo_traces_.back().time))throw runtime_error("light domain");
            q.delay_pdo_traces_.emplace_back(t,d,p);
        }
        while(getline(offsets,line)){
            istringstream h(line);unsigned int size;double value;
            if(!(h>>size>>value)||size!=100*(q.psize_latency_offset_.size()+1))throw runtime_error("offset parse");
            q.psize_latency_offset_.push_back(value);
        }
        if(q.delay_pdo_traces_.size()<3)throw runtime_error("trace length");
        ofstream out(argv[5]);if(!out)throw runtime_error("fixture output");
        out<<"packet_id,cohort,arrival_ms,content_bytes,raw_release_ms,release_ms,planned_delay_ms,base_delay_ms,light_reset,planned_light_bypass,release_clamped\n";
        if(argc==7){
            ifstream events(argv[6]);uint64_t time,id=0;unsigned int size;
            if(!events)throw runtime_error("events");
            while(events>>time>>size)q.emit(time,size,id++,0,out);
        }else{
            uint64_t cohorts=(q.delay_pdo_traces_.back().time-8000)/200000;
            for(uint64_t id=0;id<400+cohorts*10000;id++){
                // Warm-up calls still mutate the exact source state.
                if(id<400){
                    ofstream sink;
                    q.emit(id*20,stoul(argv[3]),id,0,sink);
                }else q.emit(id*20,stoul(argv[3]),id,(id-400)/10000,out);
            }
        }
        return 0;
    }catch(const exception &e){cerr<<e.what()<<endl;return 1;}
}

